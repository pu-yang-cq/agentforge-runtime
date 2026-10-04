from pathlib import Path


def method_replace(path: str, method: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    start = text.index(f"    async def {method}(")
    end = text.find("\n    async def ", start + 10)
    if end < 0:
        end = len(text)
    body = text[start:end]
    count = body.count(old)
    if count != 1:
        raise SystemExit(f"{path}:{method}: expected one anchor, found {count}: {old[:160]!r}")
    file.write_text(text[:start] + body.replace(old, new) + text[end:])


# ---------------------------------------------------------------------------
# Side-effect transient: proven no-effect + cancel means ABORT/CANCEL, no retry.
# ---------------------------------------------------------------------------
method_replace(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    "record_side_effect_transient_failure",
    '''            attempt_row.finished_at = db_now

            retry_allowed = (
''',
    '''            attempt_row.finished_at = db_now

            if run_row.cancel_requested:
                reason = "CANCEL_REQUESTED: proven side effect did not execute"
                call_row.status = ToolCallStatus.NOT_EXECUTED
                call_row.error = reason
                action_row.status = ExternalActionStatus.ABORTED
                action_row.current_attempt_id = None
                action_row.updated_at = db_now
                run_row.status = RunStatus.CANCELLED
                run_row.queue_reason = None
                run_row.available_at = None
                run_row.final_output = None
                run_row.failure_reason = None
                run_row.completed_at = db_now
                run_row.owner_worker_id = None
                run_row.lease_expires_at = None
                seqs = list(await _allocate_event_sequences(session, run.id, 3))
                session.add_all(
                    [
                        DomainEventRow(
                            id=uuid4(),
                            run_id=run.id,
                            sequence=seqs[0],
                            event_type=EventType.TOOL_FAILED.value,
                            payload={
                                "tool_call_id": str(call.id),
                                "attempt_id": str(attempt.id),
                                "attempt_number": attempt.attempt_number,
                                "error_class": "TRANSIENT",
                                "definite_not_executed": True,
                            },
                        ),
                        DomainEventRow(
                            id=uuid4(),
                            run_id=run.id,
                            sequence=seqs[1],
                            event_type=EventType.ACTION_ABORTED.value,
                            payload={
                                "external_action_id": str(action.id),
                                "operation_id": str(action.operation_id),
                                "reason": "CANCEL_REQUESTED_AFTER_PROVEN_NONEXECUTION",
                            },
                        ),
                        DomainEventRow(
                            id=uuid4(),
                            run_id=run.id,
                            sequence=seqs[2],
                            event_type=EventType.RUN_CANCELLED.value,
                            payload={},
                        ),
                    ]
                )
                attempt.fail(
                    error,
                    error_class="TRANSIENT",
                    definite_not_executed=True,
                    outcome_reason="SIDE_EFFECT_TRANSIENT_DEFINITE_NOT_EXECUTED",
                )
                call.status = ToolCallStatus.NOT_EXECUTED
                call.error = reason
                action.abort_after_definite_not_executed()
                run.cancel()
                return False

            retry_allowed = (
''',
)

# ---------------------------------------------------------------------------
# READ transient: no business retry after cancel.
# ---------------------------------------------------------------------------
method_replace(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    "record_read_transient_failure",
    '''            attempt.finished_at = db_now

            retry_allowed = (
''',
    '''            attempt.finished_at = db_now

            if row.cancel_requested:
                reason = "CANCEL_REQUESTED: READ retry suppressed"
                tool_call.status = ToolCallStatus.NOT_EXECUTED
                tool_call.error = reason
                row.status = RunStatus.CANCELLED
                row.queue_reason = None
                row.available_at = None
                row.final_output = None
                row.failure_reason = None
                row.completed_at = db_now
                row.owner_worker_id = None
                row.lease_expires_at = None
                seqs = list(await _allocate_event_sequences(session, run.id, 2))
                session.add_all(
                    [
                        DomainEventRow(
                            id=uuid4(),
                            run_id=run.id,
                            sequence=seqs[0],
                            event_type=EventType.TOOL_FAILED.value,
                            payload={
                                "tool_call_id": str(call.id),
                                "attempt_id": str(attempt.id),
                                "attempt_number": attempt.attempt_number,
                                "error_class": "TRANSIENT",
                                "definite_not_executed": True,
                                "error": call.error,
                            },
                        ),
                        DomainEventRow(
                            id=uuid4(),
                            run_id=run.id,
                            sequence=seqs[1],
                            event_type=EventType.RUN_CANCELLED.value,
                            payload={},
                        ),
                    ]
                )
                call.status = ToolCallStatus.NOT_EXECUTED
                call.error = reason
                run.cancel()
                return False

            retry_allowed = (
''',
)

# ---------------------------------------------------------------------------
# Definite side-effect failure after cancel: preserve failure fact, cancel Run.
# ---------------------------------------------------------------------------
method_replace(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    "record_side_effect_definite_failure_and_fail_run",
    '''            run_row.status = RunStatus.FAILED
            run_row.failure_reason = run.failure_reason
            run_row.completed_at = func.clock_timestamp()
            run_row.owner_worker_id = None
            run_row.lease_expires_at = None

            seqs = list(await _allocate_event_sequences(session, call.run_id, 3))
''',
    '''            cancelled = run_row.cancel_requested
            run_row.status = RunStatus.CANCELLED if cancelled else RunStatus.FAILED
            run_row.failure_reason = None if cancelled else run.failure_reason
            run_row.completed_at = func.clock_timestamp()
            run_row.owner_worker_id = None
            run_row.lease_expires_at = None

            seqs = list(await _allocate_event_sequences(session, call.run_id, 3))
''',
)

method_replace(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    "record_side_effect_definite_failure_and_fail_run",
    '''                    DomainEventRow(
                        id=uuid4(),
                        run_id=call.run_id,
                        sequence=seqs[2],
                        event_type=EventType.RUN_FAILED.value,
                        payload={"reason": run.failure_reason},
                    ),
''',
    '''                    DomainEventRow(
                        id=uuid4(),
                        run_id=call.run_id,
                        sequence=seqs[2],
                        event_type=(
                            EventType.RUN_CANCELLED.value
                            if cancelled
                            else EventType.RUN_FAILED.value
                        ),
                        payload={} if cancelled else {"reason": run.failure_reason},
                    ),
''',
)

method_replace(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    "record_side_effect_definite_failure_and_fail_run",
    '''        call.fail(error)
        action.fail_definite_not_executed()
''',
    '''        call.fail(error)
        action.fail_definite_not_executed()
        if cancelled:
            run.status = RunStatus.RUNNING
            run.failure_reason = None
            run.completed_at = None
            run.cancel()
''',
)

# ---------------------------------------------------------------------------
# Permanent READ failure after cancel: keep Tool failure evidence, cancel Run.
# ---------------------------------------------------------------------------
method_replace(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    "record_tool_failed_and_fail_run",
    '''            row.status = RunStatus.FAILED
            row.failure_reason = run.failure_reason
            row.completed_at = func.clock_timestamp()
            row.owner_worker_id = None
            row.lease_expires_at = None
''',
    '''            cancelled = row.cancel_requested
            row.status = RunStatus.CANCELLED if cancelled else RunStatus.FAILED
            row.failure_reason = None if cancelled else run.failure_reason
            row.completed_at = func.clock_timestamp()
            row.owner_worker_id = None
            row.lease_expires_at = None
''',
)

method_replace(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    "record_tool_failed_and_fail_run",
    '''                    DomainEventRow(
                        id=uuid4(),
                        run_id=call.run_id,
                        sequence=seqs[1],
                        event_type=EventType.RUN_FAILED.value,
                        payload={"reason": run.failure_reason},
                    ),
''',
    '''                    DomainEventRow(
                        id=uuid4(),
                        run_id=call.run_id,
                        sequence=seqs[1],
                        event_type=(
                            EventType.RUN_CANCELLED.value
                            if cancelled
                            else EventType.RUN_FAILED.value
                        ),
                        payload={} if cancelled else {"reason": run.failure_reason},
                    ),
''',
)

method_replace(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    "record_tool_failed_and_fail_run",
    '''            session.add_all(
                [
''',
    '''            session.add_all(
                [
''',
)  # validate method remains structurally present

# ---------------------------------------------------------------------------
# Model invocation failure after cancel: failure is evidence, cancellation owns Run.
# ---------------------------------------------------------------------------
method_replace(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    "record_model_failed_and_fail_run",
    '''            row.status = RunStatus.FAILED
            row.failure_reason = run.failure_reason
            row.completed_at = func.clock_timestamp()
            row.owner_worker_id = None
            row.lease_expires_at = None
''',
    '''            cancelled = row.cancel_requested
            row.status = RunStatus.CANCELLED if cancelled else RunStatus.FAILED
            row.failure_reason = None if cancelled else run.failure_reason
            row.completed_at = func.clock_timestamp()
            row.owner_worker_id = None
            row.lease_expires_at = None
''',
)

method_replace(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    "record_model_failed_and_fail_run",
    '''                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[1],
                        event_type=EventType.RUN_FAILED.value,
                        payload={"reason": run.failure_reason},
                    ),
''',
    '''                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[1],
                        event_type=(
                            EventType.RUN_CANCELLED.value
                            if cancelled
                            else EventType.RUN_FAILED.value
                        ),
                        payload={} if cancelled else {"reason": run.failure_reason},
                    ),
''',
)

# ---------------------------------------------------------------------------
# Reconciliation NOT_EXECUTED: cancel suppresses physical business retry.
# Use a higher-priority cancelled branch so the existing D3 retry branch stays
# byte-for-byte structurally intact.
# ---------------------------------------------------------------------------
method_replace(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    "record_reconciliation_result",
    '''            elif result.outcome is ReconciliationBusinessResult.NOT_EXECUTED and (
                binding.reconciliation_mode is ReconciliationMode.AUTHORITATIVE
                or (
                    binding.reconciliation_mode is ReconciliationMode.BEST_EFFORT
                    and binding.idempotency_supported
                )
            ):
                physical_number = int(
''',
    '''            elif (
                result.outcome is ReconciliationBusinessResult.NOT_EXECUTED
                and (
                    binding.reconciliation_mode is ReconciliationMode.AUTHORITATIVE
                    or (
                        binding.reconciliation_mode is ReconciliationMode.BEST_EFFORT
                        and binding.idempotency_supported
                    )
                )
                and run_row.cancel_requested
            ):
                action_row.status = ExternalActionStatus.ABORTED
                action_row.updated_at = db_now
                call_row.status = ToolCallStatus.NOT_EXECUTED
                call_row.error = "reconciliation proved NOT_EXECUTED after cancellation"
                run_row.status = RunStatus.CANCELLED
                run_row.queue_reason = None
                run_row.available_at = None
                run_row.final_output = None
                run_row.failure_reason = None
                run_row.completed_at = db_now
                run_row.owner_worker_id = None
                run_row.lease_expires_at = None
                session.add(
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[1],
                        event_type=EventType.ACTION_ABORTED.value,
                        payload={
                            "external_action_id": str(action.id),
                            "operation_id": str(action.operation_id),
                            "reason": "CANCEL_REQUESTED_RECONCILED_NOT_EXECUTED",
                        },
                    )
                )
                session.add(
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[2],
                        event_type=EventType.RUN_CANCELLED.value,
                        payload={},
                    )
                )

            elif result.outcome is ReconciliationBusinessResult.NOT_EXECUTED and (
                binding.reconciliation_mode is ReconciliationMode.AUTHORITATIVE
                or (
                    binding.reconciliation_mode is ReconciliationMode.BEST_EFFORT
                    and binding.idempotency_supported
                )
            ):
                physical_number = int(
''',
)

# Domain projection for safe NOT_EXECUTED after cancelled reconciliation.
method_replace(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    "record_reconciliation_result",
    '''        elif result.outcome is ReconciliationBusinessResult.NOT_EXECUTED and (
            binding.reconciliation_mode is ReconciliationMode.AUTHORITATIVE
            or (
                binding.reconciliation_mode is ReconciliationMode.BEST_EFFORT
                and binding.idempotency_supported
            )
        ):
            if run_row.status is RunStatus.QUEUED:
''',
    '''        elif result.outcome is ReconciliationBusinessResult.NOT_EXECUTED and (
            binding.reconciliation_mode is ReconciliationMode.AUTHORITATIVE
            or (
                binding.reconciliation_mode is ReconciliationMode.BEST_EFFORT
                and binding.idempotency_supported
            )
        ):
            if run_row.status is RunStatus.CANCELLED:
                action.reconcile_abort_not_executed()
                call.status = ToolCallStatus.NOT_EXECUTED
                call.error = call_row.error
                run.cancel()
            elif run_row.status is RunStatus.QUEUED:
''',
)


# Reconciliation request budget exhaustion under cancellation => terminal
# CANCELLED + MANUAL_REVIEW, while retryable reconciliation remains allowed.
method_replace(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    "record_reconciliation_failed",
    '''            action_row.status = ExternalActionStatus.MANUAL_REVIEW
            action_row.updated_at = db_now
            run_row.status = RunStatus.WAITING_ACTION_RESOLUTION
            run_row.queue_reason = None
            run_row.available_at = None
            run_row.owner_worker_id = None
            run_row.lease_expires_at = None
''',
    '''            action_row.status = ExternalActionStatus.MANUAL_REVIEW
            action_row.updated_at = db_now
            run_row.status = (
                RunStatus.CANCELLED
                if run_row.cancel_requested
                else RunStatus.WAITING_ACTION_RESOLUTION
            )
            run_row.queue_reason = None
            run_row.available_at = None
            run_row.owner_worker_id = None
            run_row.lease_expires_at = None
            if run_row.status is RunStatus.CANCELLED:
                run_row.completed_at = db_now
''',
)

method_replace(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    "record_reconciliation_failed",
    '''        action.manual_review()
        run.wait_for_action_resolution()
        return False
''',
    '''        action.manual_review()
        if run.cancel_requested:
            run.cancel()
        else:
            run.wait_for_action_resolution()
        return False
''',
)

# ---------------------------------------------------------------------------
# RunManager must treat cancel terminalization as normal cancellation, not failure.
# ---------------------------------------------------------------------------
rm = Path("src/agentforge/application/run_manager.py")
text = rm.read_text()
# Side-effect helper and both READ execution paths use two indentation levels.
for old_block, new_block in [
    (
'''            if scheduled:
                return None
            raise RunExecutionFailedError(run.failure_reason or str(exc)) from exc
''',
'''            if scheduled:
                return None
            if run.status is RunStatus.CANCELLED:
                return None
            raise RunExecutionFailedError(run.failure_reason or str(exc)) from exc
''',
    ),
    (
'''                if scheduled:
                    return None
                raise RunExecutionFailedError(run.failure_reason or str(exc)) from exc
''',
'''                if scheduled:
                    return None
                if run.status is RunStatus.CANCELLED:
                    return None
                raise RunExecutionFailedError(run.failure_reason or str(exc)) from exc
''',
    ),
]:
    text = text.replace(old_block, new_block)
if text.count("run.status is RunStatus.CANCELLED") < 3:
    raise SystemExit("expected cancellation handling on side-effect and READ transient paths")
text = text.replace(
'''                await recorder.record_side_effect_definite_failure_and_fail_run(
                    prepared.call,
                    prepared.action,
                    attempt,
                    run,
                    error=str(exc),
                    error_class=exc.error_class,
                    expected_generation=expected_generation,
                )
                raise RunExecutionFailedError(run.failure_reason) from exc
''',
'''                await recorder.record_side_effect_definite_failure_and_fail_run(
                    prepared.call,
                    prepared.action,
                    attempt,
                    run,
                    error=str(exc),
                    error_class=exc.error_class,
                    expected_generation=expected_generation,
                )
                if run.status is RunStatus.CANCELLED:
                    return None
                raise RunExecutionFailedError(run.failure_reason) from exc
''',
)
text = text.replace(
'''                await recorder.record_model_failed_and_fail_run(
                    invocation, run, expected_generation=expected_generation
                )
                raise RunExecutionFailedError(run.failure_reason) from exc
''',
'''                await recorder.record_model_failed_and_fail_run(
                    invocation, run, expected_generation=expected_generation
                )
                if run.cancel_requested:
                    run.status = RunStatus.RUNNING
                    run.failure_reason = None
                    run.completed_at = None
                    run.cancel()
                    return None
                raise RunExecutionFailedError(run.failure_reason) from exc
''',
)
# Permanent READ failure sites.
text = text.replace(
'''                await recorder.record_tool_failed_and_fail_run(
                    recoverable_call, run, expected_generation=expected_generation
                )
                raise RunExecutionFailedError(run.failure_reason) from exc
''',
'''                await recorder.record_tool_failed_and_fail_run(
                    recoverable_call, run, expected_generation=expected_generation
                )
                if run.cancel_requested:
                    run.status = RunStatus.RUNNING
                    run.failure_reason = None
                    run.completed_at = None
                    run.cancel()
                    return None
                raise RunExecutionFailedError(run.failure_reason) from exc
''',
)
text = text.replace(
'''                await recorder.record_tool_failed_and_fail_run(
                    call, run, expected_generation=expected_generation
                )
                raise RunExecutionFailedError(run.failure_reason) from exc
''',
'''                await recorder.record_tool_failed_and_fail_run(
                    call, run, expected_generation=expected_generation
                )
                if run.cancel_requested:
                    run.status = RunStatus.RUNNING
                    run.failure_reason = None
                    run.completed_at = None
                    run.cancel()
                    return None
                raise RunExecutionFailedError(run.failure_reason) from exc
''',
)
rm.write_text(text)
