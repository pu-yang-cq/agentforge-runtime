from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}: {old[:160]!r}")
    p.write_text(text.replace(old, new))


def append_once(path: str, marker: str, block: str) -> None:
    p = Path(path)
    text = p.read_text()
    if marker in text:
        raise SystemExit(f"{path}: marker already present: {marker}")
    p.write_text(text + block)


# ---------------------------------------------------------------------------
# E3: if cancellation won the Run-row race while a physical side-effect result
# was in flight, persist the external truth but permanently fence progression.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''        if action.current_attempt_id != attempt.id:
            raise ValueError("side-effect success attempt is not current")

        async with self._sessions() as session, session.begin():
            await _lock_owned_run(
                session,
                run_id=call.run_id,
                expected_generation=expected_generation,
            )
            action_row = (
''',
    '''        if action.current_attempt_id != attempt.id:
            raise ValueError("side-effect success attempt is not current")

        cancellation_fenced = False
        async with self._sessions() as session, session.begin():
            run_row = await _lock_owned_run(
                session,
                run_id=call.run_id,
                expected_generation=expected_generation,
            )
            cancellation_fenced = run_row.cancel_requested
            action_row = (
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''            seqs = list(await _allocate_event_sequences(session, call.run_id, 2))
            session.add_all(
                [
                    DomainEventRow(
                        id=uuid4(),
                        run_id=call.run_id,
                        sequence=seqs[0],
                        event_type=EventType.ACTION_SUCCEEDED.value,
                        payload={
                            "tool_call_id": str(call.id),
                            "external_action_id": str(action.id),
                            "operation_id": str(action.operation_id),
                            "attempt_id": str(attempt.id),
                        },
                    ),
                    DomainEventRow(
                        id=uuid4(),
                        run_id=call.run_id,
                        sequence=seqs[1],
                        event_type=EventType.TOOL_SUCCEEDED.value,
                        payload={
                            "tool_call_id": str(call.id),
                            "tool_name": call.tool_name,
                            "attempt_id": str(attempt.id),
                            "attempt_number": attempt.attempt_number,
                        },
                    ),
                ]
            )
            await session.flush()

        attempt.succeed(call.result)
        action.succeed()
''',
    '''            event_count = 3 if cancellation_fenced else 2
            seqs = list(await _allocate_event_sequences(session, call.run_id, event_count))
            events = [
                DomainEventRow(
                    id=uuid4(),
                    run_id=call.run_id,
                    sequence=seqs[0],
                    event_type=EventType.ACTION_SUCCEEDED.value,
                    payload={
                        "tool_call_id": str(call.id),
                        "external_action_id": str(action.id),
                        "operation_id": str(action.operation_id),
                        "attempt_id": str(attempt.id),
                    },
                ),
                DomainEventRow(
                    id=uuid4(),
                    run_id=call.run_id,
                    sequence=seqs[1],
                    event_type=EventType.TOOL_SUCCEEDED.value,
                    payload={
                        "tool_call_id": str(call.id),
                        "tool_name": call.tool_name,
                        "attempt_id": str(attempt.id),
                        "attempt_number": attempt.attempt_number,
                    },
                ),
            ]
            if cancellation_fenced:
                run_row.status = RunStatus.CANCELLED
                run_row.queue_reason = None
                run_row.available_at = None
                run_row.final_output = None
                run_row.failure_reason = None
                run_row.completed_at = func.clock_timestamp()
                run_row.owner_worker_id = None
                run_row.lease_expires_at = None
                events.append(
                    DomainEventRow(
                        id=uuid4(),
                        run_id=call.run_id,
                        sequence=seqs[2],
                        event_type=EventType.RUN_CANCELLED.value,
                        payload={"reason": "CANCEL_WON_BEFORE_SIDE_EFFECT_RESULT"},
                    )
                )
            session.add_all(events)
            await session.flush()

        if cancellation_fenced:
            raise StaleExecutorError(
                "cancellation won before side-effect result persistence; "
                "external truth was recorded but progression authority is fenced"
            )
        attempt.succeed(call.result)
        action.succeed()
''',
)


# ---------------------------------------------------------------------------
# E3: reconciliation success/failure can settle external truth after cancel,
# but cancellation remains the final Run authority and no continuation escapes.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''        self._assert_generation(expected_generation)
        returned_message: RunMessage | None = None
        async with self._sessions() as session, session.begin():
            run_row = await _lock_owned_run(
''',
    '''        self._assert_generation(expected_generation)
        returned_message: RunMessage | None = None
        cancellation_fenced = False
        async with self._sessions() as session, session.begin():
            run_row = await _lock_owned_run(
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''            if result.outcome is ReconciliationBusinessResult.SUCCEEDED:
                action_row.status = ExternalActionStatus.SUCCEEDED
                action_row.updated_at = db_now
                call_row.status = ToolCallStatus.SUCCEEDED
                call_row.error = None
                call_row.result = {
                    "reconciliation": "SUCCEEDED",
                    "evidence": result.evidence,
                }
''',
    '''            if result.outcome is ReconciliationBusinessResult.SUCCEEDED:
                action_row.status = ExternalActionStatus.SUCCEEDED
                action_row.updated_at = db_now
                call_row.status = ToolCallStatus.SUCCEEDED
                call_row.error = None
                call_row.result = {
                    "reconciliation": "SUCCEEDED",
                    "evidence": result.evidence,
                }
                if run_row.cancel_requested:
                    cancellation_fenced = True
                    run_row.status = RunStatus.CANCELLED
                    run_row.queue_reason = None
                    run_row.available_at = None
                    run_row.final_output = None
                    run_row.failure_reason = None
                    run_row.completed_at = db_now
                    run_row.owner_worker_id = None
                    run_row.lease_expires_at = None
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''            elif result.outcome is ReconciliationBusinessResult.FAILED:
                action_row.status = ExternalActionStatus.FAILED
                action_row.updated_at = db_now
                call_row.status = ToolCallStatus.FAILED
                call_row.error = "reconciliation confirmed action failure"
                run_row.status = RunStatus.FAILED
                run_row.failure_reason = "RECONCILIATION_CONFIRMED_ACTION_FAILED"
                run_row.completed_at = db_now
                run_row.owner_worker_id = None
                run_row.lease_expires_at = None
''',
    '''            elif result.outcome is ReconciliationBusinessResult.FAILED:
                action_row.status = ExternalActionStatus.FAILED
                action_row.updated_at = db_now
                call_row.status = ToolCallStatus.FAILED
                call_row.error = "reconciliation confirmed action failure"
                if run_row.cancel_requested:
                    cancellation_fenced = True
                    run_row.status = RunStatus.CANCELLED
                    run_row.queue_reason = None
                    run_row.available_at = None
                    run_row.failure_reason = None
                    run_row.final_output = None
                    run_row.completed_at = db_now
                    run_row.owner_worker_id = None
                    run_row.lease_expires_at = None
                else:
                    run_row.status = RunStatus.FAILED
                    run_row.failure_reason = "RECONCILIATION_CONFIRMED_ACTION_FAILED"
                    run_row.completed_at = db_now
                    run_row.owner_worker_id = None
                    run_row.lease_expires_at = None
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''                        event_type=EventType.RUN_FAILED.value,
                        payload={"reason": "RECONCILIATION_CONFIRMED_ACTION_FAILED"},
                    )
                )

            elif (
''',
    '''                        event_type=(
                            EventType.RUN_CANCELLED.value
                            if cancellation_fenced
                            else EventType.RUN_FAILED.value
                        ),
                        payload=(
                            {"reason": "CANCEL_WON_BEFORE_RECONCILIATION_RESULT"}
                            if cancellation_fenced
                            else {"reason": "RECONCILIATION_CONFIRMED_ACTION_FAILED"}
                        ),
                    )
                )

            elif (
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''        attempt.succeed(result.outcome, result.evidence)
        if result.outcome is ReconciliationBusinessResult.SUCCEEDED:
''',
    '''        attempt.succeed(result.outcome, result.evidence)
        if cancellation_fenced:
            run.cancel_requested = True
            if run.status is RunStatus.RUNNING:
                run.cancel()
        if result.outcome is ReconciliationBusinessResult.SUCCEEDED:
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''            call.status = ToolCallStatus.SUCCEEDED
            call.error = None
            call.result = {"reconciliation": "SUCCEEDED", "evidence": result.evidence}
        elif result.outcome is ReconciliationBusinessResult.FAILED:
''',
    '''            call.status = ToolCallStatus.SUCCEEDED
            call.error = None
            call.result = {"reconciliation": "SUCCEEDED", "evidence": result.evidence}
            if cancellation_fenced:
                return None
        elif result.outcome is ReconciliationBusinessResult.FAILED:
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''            run.owner_worker_id = None
            run.lease_expires_at = None
        elif result.outcome is ReconciliationBusinessResult.NOT_EXECUTED and (
''',
    '''            run.owner_worker_id = None
            run.lease_expires_at = None
            if cancellation_fenced:
                run.status = RunStatus.CANCELLED
                run.failure_reason = None
                return None
        elif result.outcome is ReconciliationBusinessResult.NOT_EXECUTED and (
''',
)


# ---------------------------------------------------------------------------
# E3 integration coverage.
# ---------------------------------------------------------------------------
replace_once(
    "tests/integration/test_postgres_runtime.py",
    '''    ReconciliationBusinessResult,
    RunStatus,
''',
    '''    ReconciliationBusinessResult,
    MessageRole,
    RunStatus,
''',
)

replace_once(
    "tests/integration/test_postgres_runtime.py",
    '''from agentforge.domain.models import ToolProposal
''',
    '''from agentforge.domain.models import RunMessage, ToolProposal
''',
)

append_once(
    "tests/integration/test_postgres_runtime.py",
    "_prepare_e3_inflight_side_effect",
    r'''


async def _prepare_e3_inflight_side_effect(
    sessions,
    *,
    key: str,
    tool_name: str,
    reconciliation_mode=None,
):
    from agentforge.domain.enums import ReconciliationMode

    mode = reconciliation_mode or ReconciliationMode.AUTHORITATIVE
    side_tool_id = uuid4()
    side_version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(ToolDefinitionRow(id=side_tool_id, name=tool_name, description="e3 write"))
        await session.flush()
        session.add(
            ToolVersionRow(
                id=side_version_id,
                tool_id=side_tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.EXTERNAL_SIDE_EFFECT,
                implementation_ref=f"tests:{tool_name}",
                allow_no_approval_execution=True,
                reconciliation_mode=mode,
                reconciliation_max_attempts=2,
                reconciliation_initial_backoff_seconds=0,
                reconciliation_max_backoff_seconds=0,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=DEMO_AGENT_VERSION_ID,
                tool_version_id=side_version_id,
                tool_alias=tool_name,
            )
        )

    registry = InMemoryToolRegistry(
        [
            FunctionTool(
                version_id=DEMO_TOOL_VERSION_ID,
                name="echo_read",
                description="read",
                input_schema={"type": "object"},
                func=lambda text: {"echo": text},
            ),
            SideEffectFunctionTool(
                version_id=side_version_id,
                name=tool_name,
                description="e3 write",
                input_schema={"type": "object"},
                func=lambda invocation: {"operation_id": str(invocation.operation_id), "ok": True},
                reconcile_func=lambda invocation: ReconciliationResult(
                    ReconciliationBusinessResult.SUCCEEDED,
                    {"operation_id": str(invocation.operation_id)},
                ),
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text=f"e3 {tool_name}",
        idempotency_key=key,
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id=f"{tool_name}-worker", lease_seconds=30)
    assert claimed is not None
    recorder = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed.execution_generation,
    )
    _, invocation = await recorder.begin_model_invocation(
        run_id=created.id,
        invocation_id=uuid4(),
        expected_generation=claimed.execution_generation,
    )
    invocation.complete("TOOL_PROPOSAL")
    proposal = ToolProposal.create(
        run_id=created.id,
        model_invocation_id=invocation.id,
        tool_name=tool_name,
        arguments={"v": 1},
    )
    version = await store.load_agent_version(DEMO_AGENT_VERSION_ID)
    prepared = ToolCoordinator(registry).prepare_side_effect(
        proposal=proposal,
        agent_version=version,
    )
    await recorder.record_model_side_effect_prepared(
        invocation,
        proposal,
        prepared.call,
        prepared.snapshot,
        prepared.action,
        expected_generation=claimed.execution_generation,
    )
    attempt = await recorder.record_side_effect_attempt_started(
        prepared.call,
        prepared.action,
        expected_generation=claimed.execution_generation,
    )
    return store, claimed, recorder, prepared, attempt, version


@pytest.mark.asyncio
async def test_e3_result_wins_then_cancellation_does_not_rollback_succeeded_action() -> None:
    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store, claimed, recorder, prepared, attempt, _ = await _prepare_e3_inflight_side_effect(
        sessions,
        key="integration-e3-result-wins",
        tool_name="e3_result_wins",
    )

    prepared.call = await ToolCoordinator(
        InMemoryToolRegistry([prepared.tool])
    ).execute_side_effect(prepared, attempt)
    message = RunMessage(
        claimed.id,
        0,
        MessageRole.TOOL,
        '{"ok":true}',
        prepared.call.id,
    )
    await recorder.record_side_effect_succeeded(
        prepared.call,
        prepared.action,
        attempt,
        message,
        expected_generation=claimed.execution_generation,
    )

    cancelled = await store.cancel_run(claimed.id)
    assert cancelled.status is RunStatus.CANCELLED
    assert cancelled.cancel_requested is True
    async with sessions() as session:
        action = await session.get(ExternalActionRow, prepared.action.id)
        call = await session.get(ToolCallRow, prepared.call.id)
        durable_attempt = await session.get(ToolExecutionAttemptRow, attempt.id)
    assert action is not None and action.status is ExternalActionStatus.SUCCEEDED
    assert call is not None and call.status is ToolCallStatus.SUCCEEDED
    assert durable_attempt is not None
    assert durable_attempt.status is ToolExecutionAttemptStatus.SUCCEEDED
    await engine.dispose()


@pytest.mark.asyncio
async def test_e3_cancellation_wins_inflight_side_effect_result_records_truth_but_fences_worker() -> None:
    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store, claimed, recorder, prepared, attempt, _ = await _prepare_e3_inflight_side_effect(
        sessions,
        key="integration-e3-cancel-wins",
        tool_name="e3_cancel_wins",
    )

    cancel_state = await store.cancel_run(claimed.id)
    assert cancel_state.cancel_requested is True
    assert cancel_state.status is RunStatus.RUNNING

    prepared.call = await ToolCoordinator(
        InMemoryToolRegistry([prepared.tool])
    ).execute_side_effect(prepared, attempt)
    message = RunMessage(
        claimed.id,
        0,
        MessageRole.TOOL,
        '{"ok":true}',
        prepared.call.id,
    )
    with pytest.raises(StaleExecutorError, match="progression authority is fenced"):
        await recorder.record_side_effect_succeeded(
            prepared.call,
            prepared.action,
            attempt,
            message,
            expected_generation=claimed.execution_generation,
        )

    durable = await store.get_run(claimed.id)
    assert durable is not None
    assert durable.status is RunStatus.CANCELLED
    assert durable.cancel_requested is True
    async with sessions() as session:
        action = await session.get(ExternalActionRow, prepared.action.id)
        call = await session.get(ToolCallRow, prepared.call.id)
        durable_attempt = await session.get(ToolExecutionAttemptRow, attempt.id)
        event_types = (
            (
                await session.execute(
                    select(DomainEventRow.event_type)
                    .where(DomainEventRow.run_id == claimed.id)
                    .order_by(DomainEventRow.sequence)
                )
            )
            .scalars()
            .all()
        )
    assert action is not None and action.status is ExternalActionStatus.SUCCEEDED
    assert call is not None and call.status is ToolCallStatus.SUCCEEDED
    assert durable_attempt is not None
    assert durable_attempt.status is ToolExecutionAttemptStatus.SUCCEEDED
    assert EventType.RUN_CANCELLED.value in event_types
    await engine.dispose()


@pytest.mark.asyncio
async def test_e3_cancellation_wins_reconciliation_success_truth_without_continuation() -> None:
    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store, claimed, recorder, prepared, attempt, version = await _prepare_e3_inflight_side_effect(
        sessions,
        key="integration-e3-cancel-reconcile",
        tool_name="e3_cancel_reconcile",
    )

    await recorder.record_side_effect_unknown(
        prepared.call,
        prepared.action,
        attempt,
        error="response lost",
        error_class="RESPONSE_LOST",
        outcome_reason="SIDE_EFFECT_POSSIBLE_EXECUTION",
        expected_generation=claimed.execution_generation,
    )
    binding = next(
        item for item in version.tool_bindings if item.name == "e3_cancel_reconcile"
    )
    reconciliation = await recorder.record_reconciliation_started(
        prepared.call,
        prepared.action,
        claimed,
        max_attempts=binding.reconciliation_max_attempts,
        expected_generation=claimed.execution_generation,
    )
    assert reconciliation is not None

    cancel_state = await store.cancel_run(claimed.id)
    assert cancel_state.status is RunStatus.RUNNING
    assert cancel_state.cancel_requested is True

    returned = await recorder.record_reconciliation_result(
        prepared.call,
        prepared.action,
        reconciliation,
        claimed,
        ReconciliationResult(
            ReconciliationBusinessResult.SUCCEEDED,
            {"provider": "confirmed"},
        ),
        binding=binding,
        expected_generation=claimed.execution_generation,
    )
    assert returned is None

    durable = await store.get_run(claimed.id)
    assert durable is not None
    assert durable.status is RunStatus.CANCELLED
    assert durable.cancel_requested is True
    async with sessions() as session:
        action = await session.get(ExternalActionRow, prepared.action.id)
        call = await session.get(ToolCallRow, prepared.call.id)
        recon = await session.get(ReconciliationAttemptRow, reconciliation.id)
    assert action is not None and action.status is ExternalActionStatus.SUCCEEDED
    assert call is not None and call.status is ToolCallStatus.SUCCEEDED
    assert recon is not None
    assert recon.status is ReconciliationAttemptStatus.SUCCEEDED
    assert recon.business_result is ReconciliationBusinessResult.SUCCEEDED
    await engine.dispose()


@pytest.mark.asyncio
async def test_e3_manual_resolution_wins_late_stale_result_cannot_overwrite() -> None:
    from agentforge.domain.actions import ExternalAction
    from agentforge.domain.models import ToolCall, ToolExecutionAttempt

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store, run_id, action_id, _ = await _build_manual_review_run_for_e2(
        sessions,
        key="integration-e3-resolution-wins",
        tool_name="e3_resolution_wins",
    )

    resolved_run, resolution = await store.resolve_action(
        run_id=run_id,
        action_id=action_id,
        outcome=ActionResolutionOutcome.SUCCEEDED,
        evidence={"operator": "verified"},
        reason="manual truth wins",
        resolver_identity="operator:e3",
    )
    assert resolved_run.status is RunStatus.QUEUED

    async with sessions() as session:
        action_row = await session.get(ExternalActionRow, action_id)
        assert action_row is not None
        call_row = await session.get(ToolCallRow, action_row.tool_call_id)
        assert call_row is not None

    fake_attempt_id = uuid4()
    late_call = ToolCall(
        call_row.id,
        run_id,
        call_row.proposal_id,
        call_row.tool_version_id,
        call_row.tool_name,
        dict(call_row.arguments),
        status=ToolCallStatus.SUCCEEDED,
        result={"late": "provider-success"},
    )
    late_action = ExternalAction(
        action_row.id,
        run_id,
        action_row.tool_call_id,
        action_row.action_snapshot_id,
        action_row.operation_id,
        status=ExternalActionStatus.EXECUTING,
        current_attempt_id=fake_attempt_id,
    )
    late_attempt = ToolExecutionAttempt(
        fake_attempt_id,
        run_id,
        call_row.id,
        99,
        1,
        external_action_id=action_id,
    )
    stale_recorder = PostgresExecutionRecorder(sessions, run_id=run_id, generation=1)
    with pytest.raises(StaleExecutorError):
        await stale_recorder.record_side_effect_succeeded(
            late_call,
            late_action,
            late_attempt,
            RunMessage(run_id, 0, MessageRole.TOOL, '{"late":true}', call_row.id),
            expected_generation=1,
        )

    async with sessions() as session:
        final_action = await session.get(ExternalActionRow, action_id)
        final_call = await session.get(ToolCallRow, call_row.id)
        final_resolution = await session.get(ActionResolutionRow, resolution.id)
    assert final_action is not None
    assert final_action.status is ExternalActionStatus.SUCCEEDED
    assert final_call is not None
    assert final_call.status is ToolCallStatus.SUCCEEDED
    assert final_call.result == {
        "manual_resolution": ActionResolutionOutcome.SUCCEEDED.value,
        "evidence": {"operator": "verified"},
    }
    assert final_resolution is not None
    assert final_resolution.outcome is ActionResolutionOutcome.SUCCEEDED
    await engine.dispose()
'''
)
