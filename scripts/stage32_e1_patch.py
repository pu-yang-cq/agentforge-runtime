from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}: {old[:160]!r}")
    file.write_text(text.replace(old, new))


def append_text(path: str, marker: str, block: str) -> None:
    file = Path(path)
    text = file.read_text()
    if marker in text:
        raise SystemExit(f"{path}: marker already present: {marker}")
    file.write_text(text + block)


# ---------------------------------------------------------------------------
# Domain: cancellation is orthogonal durable intent, not rollback.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/domain/enums.py",
    '''    RUN_STARTED = "RUN_STARTED"
    MODEL_STARTED = "MODEL_STARTED"
''',
    '''    RUN_STARTED = "RUN_STARTED"
    RUN_CANCEL_REQUESTED = "RUN_CANCEL_REQUESTED"
    RUN_CANCELLED = "RUN_CANCELLED"
    MODEL_STARTED = "MODEL_STARTED"
''',
)

replace_once(
    "src/agentforge/domain/models.py",
    '''    final_output: str | None = None
    failure_reason: str | None = None
    execution_generation: int = 0
''',
    '''    final_output: str | None = None
    failure_reason: str | None = None
    cancel_requested: bool = False
    execution_generation: int = 0
''',
)

replace_once(
    "src/agentforge/domain/models.py",
    '''    def wait_for_action_resolution(self) -> None:
        if self.status is not RunStatus.RUNNING:
            raise ValueError(f"cannot wait for action resolution from {self.status}")
        self.status = RunStatus.WAITING_ACTION_RESOLUTION
        self.queue_reason = None
        self.available_at = None
        self.owner_worker_id = None
        self.lease_expires_at = None


@dataclass(slots=True)
class RunState:
''',
    '''    def wait_for_action_resolution(self) -> None:
        if self.status is not RunStatus.RUNNING:
            raise ValueError(f"cannot wait for action resolution from {self.status}")
        self.status = RunStatus.WAITING_ACTION_RESOLUTION
        self.queue_reason = None
        self.available_at = None
        self.owner_worker_id = None
        self.lease_expires_at = None

    def request_cancel(self) -> None:
        if self.status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
            return
        self.cancel_requested = True

    def cancel(self) -> None:
        if self.status in {RunStatus.COMPLETED, RunStatus.FAILED}:
            raise ValueError(f"cannot cancel terminal run from {self.status}")
        self.cancel_requested = True
        self.status = RunStatus.CANCELLED
        self.queue_reason = None
        self.available_at = None
        self.final_output = None
        self.failure_reason = None
        self.owner_worker_id = None
        self.lease_expires_at = None
        self.completed_at = utcnow()


@dataclass(slots=True)
class RunState:
''',
)


# ---------------------------------------------------------------------------
# Persistence: cancel_requested column and ORM projection.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/infrastructure/db/models.py",
    '''    failure_reason: Mapped[str | None] = mapped_column(Text)
    execution_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
''',
    '''    failure_reason: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    execution_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
''',
)

replace_once(
    "src/agentforge/infrastructure/db/models.py",
    '''            "status NOT IN ('CREATED', 'QUEUED', 'RUNNING') OR completed_at IS NULL",
''',
    '''            "status NOT IN ('CREATED', 'QUEUED', 'RUNNING', 'WAITING_ACTION_RESOLUTION') "
            "OR completed_at IS NULL",
''',
)

replace_once(
    "src/agentforge/infrastructure/db/mappers.py",
    '''        final_output=row.final_output,
        failure_reason=row.failure_reason,
        execution_generation=row.execution_generation,
''',
    '''        final_output=row.final_output,
        failure_reason=row.failure_reason,
        cancel_requested=row.cancel_requested,
        execution_generation=row.execution_generation,
''',
)

Path("migrations/versions/0014_cancellation_intent.py").write_text(
    '''"""add durable cancellation intent

Revision ID: 0014_cancellation_intent
Revises: 0013_reconciliation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_cancellation_intent"
down_revision: str | None = "0013_reconciliation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column(
            "cancel_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.alter_column("runs", "cancel_requested", server_default=None)


def downgrade() -> None:
    op.drop_column("runs", "cancel_requested")
'''
)


# ---------------------------------------------------------------------------
# RuntimeStore cancellation API.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/application/ports.py",
    '''    async def get_run(self, run_id: UUID) -> Run | None: ...

    async def claim_next_run(self, *, worker_id: str, lease_seconds: int) -> Run | None: ...
''',
    '''    async def get_run(self, run_id: UUID) -> Run | None: ...

    async def cancel_run(self, run_id: UUID) -> Run: ...

    async def claim_next_run(self, *, worker_id: str, lease_seconds: int) -> Run | None: ...
''',
)

# Cancellation must use the same Run serialization point as claims/progression.
replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''    async def claim_next_run(self, *, worker_id: str, lease_seconds: int) -> Run | None:
''',
    '''    async def cancel_run(self, run_id: UUID) -> Run:
        async with self._sessions() as session, session.begin():
            row = (
                await session.execute(
                    select(RunRow).where(RunRow.id == run_id).with_for_update()
                )
            ).scalar_one_or_none()
            if row is None:
                raise KeyError(f"run not found: {run_id}")
            if row.status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
                return run_from_row(row)

            row.cancel_requested = True
            events: list[tuple[EventType, dict[str, object]]] = [
                (EventType.RUN_CANCEL_REQUESTED, {})
            ]

            action = (
                await session.execute(
                    select(ExternalActionRow)
                    .where(ExternalActionRow.run_id == run_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()

            # Cancel before Action Commit is a local DB stabilization, never rollback.
            if action is not None and action.status is ExternalActionStatus.READY:
                call = (
                    await session.execute(
                        select(ToolCallRow)
                        .where(
                            ToolCallRow.id == action.tool_call_id,
                            ToolCallRow.run_id == run_id,
                        )
                        .with_for_update()
                    )
                ).scalar_one()
                started = await session.scalar(
                    select(ToolExecutionAttemptRow.id)
                    .where(
                        ToolExecutionAttemptRow.external_action_id == action.id,
                        ToolExecutionAttemptRow.status == ToolExecutionAttemptStatus.STARTED,
                    )
                    .limit(1)
                )
                if started is not None or action.current_attempt_id is not None:
                    raise RuntimeError("READY ExternalAction unexpectedly has active attempt")
                if call.status is not ToolCallStatus.READY:
                    raise RuntimeError("READY ExternalAction does not project to READY ToolCall")
                action.status = ExternalActionStatus.ABORTED
                action.updated_at = func.clock_timestamp()
                call.status = ToolCallStatus.NOT_EXECUTED
                call.error = "CANCEL_REQUESTED: action aborted before Action Commit"
                events.append(
                    (
                        EventType.ACTION_ABORTED,
                        {
                            "external_action_id": str(action.id),
                            "operation_id": str(action.operation_id),
                            "reason": "CANCEL_REQUESTED_BEFORE_ACTION_COMMIT",
                        },
                    )
                )

            # Stabilize any recovered/prepared non-side-effect READY call too.
            ready_calls = (
                (
                    await session.execute(
                        select(ToolCallRow)
                        .outerjoin(
                            ExternalActionRow,
                            ExternalActionRow.tool_call_id == ToolCallRow.id,
                        )
                        .where(
                            ToolCallRow.run_id == run_id,
                            ToolCallRow.status == ToolCallStatus.READY,
                            ExternalActionRow.id.is_(None),
                        )
                        .with_for_update()
                    )
                )
                .scalars()
                .all()
            )
            for call in ready_calls:
                call.status = ToolCallStatus.NOT_EXECUTED
                call.error = "CANCEL_REQUESTED: READY business work discarded"

            active_model = await session.scalar(
                select(ModelInvocationRow.id)
                .where(
                    ModelInvocationRow.run_id == run_id,
                    ModelInvocationRow.status == ModelInvocationStatus.STARTED.value,
                )
                .limit(1)
            )
            active_tool = await session.scalar(
                select(ToolExecutionAttemptRow.id)
                .where(
                    ToolExecutionAttemptRow.run_id == run_id,
                    ToolExecutionAttemptRow.status == ToolExecutionAttemptStatus.STARTED,
                )
                .limit(1)
            )
            active_reconciliation = await session.scalar(
                select(ReconciliationAttemptRow.id)
                .where(
                    ReconciliationAttemptRow.run_id == run_id,
                    ReconciliationAttemptRow.status == ReconciliationAttemptStatus.STARTED,
                )
                .limit(1)
            )

            stable_action = action is None or action.status in {
                ExternalActionStatus.SUCCEEDED,
                ExternalActionStatus.FAILED,
                ExternalActionStatus.ABORTED,
                ExternalActionStatus.MANUAL_REVIEW,
            }
            if (
                active_model is None
                and active_tool is None
                and active_reconciliation is None
                and stable_action
            ):
                row.status = RunStatus.CANCELLED
                row.queue_reason = None
                row.available_at = None
                row.final_output = None
                row.failure_reason = None
                row.completed_at = func.clock_timestamp()
                row.owner_worker_id = None
                row.lease_expires_at = None
                events.append((EventType.RUN_CANCELLED, {}))

            seqs = list(await _allocate_event_sequences(session, run_id, len(events)))
            for seq, (event_type, payload) in zip(seqs, events, strict=True):
                session.add(
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run_id,
                        sequence=seq,
                        event_type=event_type.value,
                        payload=payload,
                    )
                )
            await session.flush()
            await session.refresh(row)
            return run_from_row(row)

    async def claim_next_run(self, *, worker_id: str, lease_seconds: int) -> Run | None:
''',
)


# ---------------------------------------------------------------------------
# Recorder guards and cancellation terminalization.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''def _assert_model_budget(run: RunRow, state: RunStateRow) -> None:
''',
    '''def _assert_business_progression_allowed(run: RunRow) -> None:
    if run.cancel_requested:
        raise BusinessProgressionBlockedError(
            "CANCEL_REQUESTED",
            "run cancellation owns business progression",
        )


def _assert_model_budget(run: RunRow, state: RunStateRow) -> None:
''',
)

# Add cancellation guard to business-start transactions by inserting directly
# after their owned Run lock. Specific anchors keep safety-work reconciliation
# deliberately exempt.
for anchor in [
    '''            run_row = await _lock_owned_run(
                session,
                run_id=call.run_id,
                expected_generation=expected_generation,
            )
            action_row = (
''',
]:
    # First occurrence is Action Commit. Only replace one.
    replace_once(
        "src/agentforge/infrastructure/db/execution_recorder.py",
        anchor,
        '''            run_row = await _lock_owned_run(
                session,
                run_id=call.run_id,
                expected_generation=expected_generation,
            )
            _assert_business_progression_allowed(run_row)
            action_row = (
''',
    )

# record_recovered_read_started
replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''            run_row = await _lock_owned_run(
                session,
                run_id=call.run_id,
                expected_generation=expected_generation,
            )
            await _assert_no_active_tool_calls(session, call.run_id)
            await _assert_no_started_tool_attempts(session, call.run_id)
            state = await _lock_run_state(session, call.run_id)
''',
    '''            run_row = await _lock_owned_run(
                session,
                run_id=call.run_id,
                expected_generation=expected_generation,
            )
            _assert_business_progression_allowed(run_row)
            await _assert_no_active_tool_calls(session, call.run_id)
            await _assert_no_started_tool_attempts(session, call.run_id)
            state = await _lock_run_state(session, call.run_id)
''',
)

# begin_model_invocation
replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''            row = await _lock_owned_run(
                session, run_id=run_id, expected_generation=expected_generation
            )
            await _assert_no_active_tool_calls(session, run_id)
            await _assert_no_started_tool_attempts(session, run_id)
            await _assert_no_started_model_invocations(session, run_id)
''',
    '''            row = await _lock_owned_run(
                session, run_id=run_id, expected_generation=expected_generation
            )
            _assert_business_progression_allowed(row)
            await _assert_no_active_tool_calls(session, run_id)
            await _assert_no_started_tool_attempts(session, run_id)
            await _assert_no_started_model_invocations(session, run_id)
''',
)

# READ proposal consequence / side-effect preparation both have dedicated
# deadline/budget checks; add cancel guard after the locked run.
replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''            run_row = await _lock_owned_run(
                session,
                run_id=call.run_id,
                expected_generation=expected_generation,
            )
            await _assert_no_active_tool_calls(session, call.run_id)
            await _assert_deadline_not_expired(session, run_row)
            state = await _lock_run_state(session, call.run_id)
''',
    '''            run_row = await _lock_owned_run(
                session,
                run_id=call.run_id,
                expected_generation=expected_generation,
            )
            _assert_business_progression_allowed(run_row)
            await _assert_no_active_tool_calls(session, call.run_id)
            await _assert_deadline_not_expired(session, run_row)
            state = await _lock_run_state(session, call.run_id)
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''            run_row = await _lock_owned_run(
                session,
                run_id=call.run_id,
                expected_generation=expected_generation,
            )
            await _assert_no_active_tool_calls(session, call.run_id)
            await _assert_no_started_tool_attempts(session, call.run_id)
            state = await _lock_run_state(session, call.run_id)
''',
    '''            run_row = await _lock_owned_run(
                session,
                run_id=call.run_id,
                expected_generation=expected_generation,
            )
            _assert_business_progression_allowed(run_row)
            await _assert_no_active_tool_calls(session, call.run_id)
            await _assert_no_started_tool_attempts(session, call.run_id)
            state = await _lock_run_state(session, call.run_id)
''',
)

# New recorder operations used when cancellation blocks a model consequence or
# when stable in-flight work reaches the cancellation boundary.
replace_once(
    "src/agentforge/application/ports.py",
    '''    async def record_model_result_discarded_and_fail_run(
        self,
        invocation: ModelInvocation,
        run: Run,
        reason: str,
        *,
        expected_generation: int,
    ) -> None: ...
''',
    '''    async def record_model_result_discarded_and_fail_run(
        self,
        invocation: ModelInvocation,
        run: Run,
        reason: str,
        *,
        expected_generation: int,
    ) -> None: ...

    async def record_model_result_discarded_and_cancel_run(
        self,
        invocation: ModelInvocation,
        run: Run,
        reason: str,
        *,
        expected_generation: int,
    ) -> None: ...

    async def record_run_cancelled(
        self,
        run: Run,
        *,
        expected_generation: int,
    ) -> None: ...
''',
)

# In-memory journal implementations.
replace_once(
    "src/agentforge/application/run_manager.py",
    '''    async def record_model_failed_and_fail_run(
        self,
        invocation: ModelInvocation,
        run: Run,
''',
    '''    async def record_model_result_discarded_and_cancel_run(
        self,
        invocation: ModelInvocation,
        run: Run,
        reason: str,
        *,
        expected_generation: int,
    ) -> None:
        self._persist_completed_invocation(invocation)
        run.cancel()
        self._append_event(
            run,
            EventType.MODEL_RESULT_DISCARDED,
            {"invocation_id": str(invocation.id), "reason": reason},
        )
        self._append_event(run, EventType.RUN_CANCELLED, {})

    async def record_run_cancelled(
        self,
        run: Run,
        *,
        expected_generation: int,
    ) -> None:
        run.cancel()
        self._append_event(run, EventType.RUN_CANCELLED, {})

    async def record_model_failed_and_fail_run(
        self,
        invocation: ModelInvocation,
        run: Run,
''',
)

# Postgres implementation before record_model_failed...
replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''    async def record_model_failed_and_fail_run(
        self,
        invocation: ModelInvocation,
        run: Run,
''',
    '''    async def record_model_result_discarded_and_cancel_run(
        self,
        invocation: ModelInvocation,
        run: Run,
        reason: str,
        *,
        expected_generation: int,
    ) -> None:
        self._assert_generation(expected_generation)
        async with self._sessions() as session, session.begin():
            row = await _lock_owned_run(
                session,
                run_id=run.id,
                expected_generation=expected_generation,
            )
            if not row.cancel_requested:
                raise RuntimeError("cancel-discard requires durable cancel_requested")
            result = await session.execute(
                update(ModelInvocationRow)
                .where(
                    ModelInvocationRow.id == invocation.id,
                    ModelInvocationRow.run_id == run.id,
                    ModelInvocationRow.status == ModelInvocationStatus.STARTED.value,
                )
                .values(
                    status=invocation.status.value,
                    outcome_type=invocation.outcome_type,
                    completed_at=func.clock_timestamp(),
                )
            )
            if cast(CursorResult[Any], result).rowcount != 1:
                raise RuntimeError("model invocation no longer STARTED")
            row.status = RunStatus.CANCELLED
            row.queue_reason = None
            row.available_at = None
            row.final_output = None
            row.failure_reason = None
            row.completed_at = func.clock_timestamp()
            row.owner_worker_id = None
            row.lease_expires_at = None
            seqs = list(await _allocate_event_sequences(session, run.id, 3))
            session.add_all(
                [
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[0],
                        event_type=EventType.MODEL_COMPLETED.value,
                        payload={
                            "turn": invocation.turn,
                            "outcome_type": invocation.outcome_type,
                        },
                    ),
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[1],
                        event_type=EventType.MODEL_RESULT_DISCARDED.value,
                        payload={
                            "invocation_id": str(invocation.id),
                            "reason": reason,
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
        run.cancel()

    async def record_run_cancelled(
        self,
        run: Run,
        *,
        expected_generation: int,
    ) -> None:
        self._assert_generation(expected_generation)
        async with self._sessions() as session, session.begin():
            row = await _lock_owned_run(
                session,
                run_id=run.id,
                expected_generation=expected_generation,
            )
            if not row.cancel_requested:
                raise RuntimeError("run cancellation finalization requires cancel_requested")
            unresolved = await session.scalar(
                select(ExternalActionRow.id)
                .where(
                    ExternalActionRow.run_id == run.id,
                    ExternalActionRow.status.in_(
                        [
                            ExternalActionStatus.READY,
                            ExternalActionStatus.EXECUTING,
                            ExternalActionStatus.UNKNOWN,
                            ExternalActionStatus.RECONCILING,
                        ]
                    ),
                )
                .limit(1)
            )
            if unresolved is not None:
                raise RuntimeError("cannot terminalize cancellation with unresolved active action")
            await _assert_no_started_tool_attempts(session, run.id)
            await _assert_no_started_model_invocations(session, run.id)
            started_reconciliation = await session.scalar(
                select(ReconciliationAttemptRow.id)
                .where(
                    ReconciliationAttemptRow.run_id == run.id,
                    ReconciliationAttemptRow.status == ReconciliationAttemptStatus.STARTED,
                )
                .limit(1)
            )
            if started_reconciliation is not None:
                raise RuntimeError("cannot terminalize cancellation with STARTED reconciliation")
            row.status = RunStatus.CANCELLED
            row.queue_reason = None
            row.available_at = None
            row.final_output = None
            row.failure_reason = None
            row.completed_at = func.clock_timestamp()
            row.owner_worker_id = None
            row.lease_expires_at = None
            seq = next(iter(await _allocate_event_sequences(session, run.id, 1)))
            session.add(
                DomainEventRow(
                    id=uuid4(),
                    run_id=run.id,
                    sequence=seq,
                    event_type=EventType.RUN_CANCELLED.value,
                    payload={},
                )
            )
        run.cancel()

    async def record_model_failed_and_fail_run(
        self,
        invocation: ModelInvocation,
        run: Run,
''',
)


# ---------------------------------------------------------------------------
# RunManager cancellation-aware consequence handling.
# ---------------------------------------------------------------------------
# At top of execute, sync durable cancellation carried by claimed Run.
replace_once(
    "src/agentforge/application/run_manager.py",
    '''        expected_generation = run.execution_generation
        messages = await recorder.list_messages(run.id)
''',
    '''        expected_generation = run.execution_generation
        messages = await recorder.list_messages(run.id)
''',
)  # explicit no-op anchor validates location

# begin_model_invocation cancellation becomes CANCELLED, not FAILED.
replace_once(
    "src/agentforge/application/run_manager.py",
    '''            except BusinessProgressionBlockedError as exc:
                run.fail(exc.failure_reason)
                await recorder.record_run_failed(
                    run,
                    expected_generation=expected_generation,
                )
                raise RunExecutionFailedError(run.failure_reason) from exc
            try:
                decision = await self._runner.decide_prepared(request)
''',
    '''            except BusinessProgressionBlockedError as exc:
                if exc.code == "CANCEL_REQUESTED":
                    run.request_cancel()
                    await recorder.record_run_cancelled(
                        run,
                        expected_generation=expected_generation,
                    )
                    return None
                run.fail(exc.failure_reason)
                await recorder.record_run_failed(
                    run,
                    expected_generation=expected_generation,
                )
                raise RunExecutionFailedError(run.failure_reason) from exc
            try:
                decision = await self._runner.decide_prepared(request)
''',
)

# Final model consequence cancellation.
replace_once(
    "src/agentforge/application/run_manager.py",
    '''                except BusinessProgressionBlockedError as exc:
                    run.fail(exc.failure_reason)
                    await recorder.record_model_result_discarded_and_fail_run(
                        invocation,
                        run,
                        exc.failure_reason,
                        expected_generation=expected_generation,
                    )
                    raise RunExecutionFailedError(run.failure_reason) from exc
                run.complete(decision.text)
''',
    '''                except BusinessProgressionBlockedError as exc:
                    if exc.code == "CANCEL_REQUESTED":
                        run.request_cancel()
                        await recorder.record_model_result_discarded_and_cancel_run(
                            invocation,
                            run,
                            exc.failure_reason,
                            expected_generation=expected_generation,
                        )
                        return None
                    run.fail(exc.failure_reason)
                    await recorder.record_model_result_discarded_and_fail_run(
                        invocation,
                        run,
                        exc.failure_reason,
                        expected_generation=expected_generation,
                    )
                    raise RunExecutionFailedError(run.failure_reason) from exc
                run.complete(decision.text)
''',
)

# Side-effect proposal persistence cancellation.
replace_once(
    "src/agentforge/application/run_manager.py",
    '''                except BusinessProgressionBlockedError as exc:
                    run.fail(exc.failure_reason)
                    await recorder.record_model_result_discarded_and_fail_run(
                        invocation,
                        run,
                        exc.failure_reason,
                        expected_generation=expected_generation,
                    )
                    raise RunExecutionFailedError(run.failure_reason) from exc
                side_effect_message = await self._execute_side_effect_action(
''',
    '''                except BusinessProgressionBlockedError as exc:
                    if exc.code == "CANCEL_REQUESTED":
                        run.request_cancel()
                        await recorder.record_model_result_discarded_and_cancel_run(
                            invocation,
                            run,
                            exc.failure_reason,
                            expected_generation=expected_generation,
                        )
                        return None
                    run.fail(exc.failure_reason)
                    await recorder.record_model_result_discarded_and_fail_run(
                        invocation,
                        run,
                        exc.failure_reason,
                        expected_generation=expected_generation,
                    )
                    raise RunExecutionFailedError(run.failure_reason) from exc
                side_effect_message = await self._execute_side_effect_action(
''',
)

# READ proposal persistence cancellation.
replace_once(
    "src/agentforge/application/run_manager.py",
    '''            except BusinessProgressionBlockedError as exc:
                run.fail(exc.failure_reason)
                await recorder.record_model_result_discarded_and_fail_run(
                    invocation,
                    run,
                    exc.failure_reason,
                    expected_generation=expected_generation,
                )
                raise RunExecutionFailedError(run.failure_reason) from exc
            try:
                call = await self._tools.execute_prepared(prepared)
''',
    '''            except BusinessProgressionBlockedError as exc:
                if exc.code == "CANCEL_REQUESTED":
                    run.request_cancel()
                    await recorder.record_model_result_discarded_and_cancel_run(
                        invocation,
                        run,
                        exc.failure_reason,
                        expected_generation=expected_generation,
                    )
                    return None
                run.fail(exc.failure_reason)
                await recorder.record_model_result_discarded_and_fail_run(
                    invocation,
                    run,
                    exc.failure_reason,
                    expected_generation=expected_generation,
                )
                raise RunExecutionFailedError(run.failure_reason) from exc
            try:
                call = await self._tools.execute_prepared(prepared)
''',
)


# ---------------------------------------------------------------------------
# Consequence methods must observe cancellation while still authorized.
# ---------------------------------------------------------------------------
# Final decision persistence: reject consequence after locking current Run.
replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''            row = await _lock_owned_run(
                session, run_id=run.id, expected_generation=expected_generation
            )
            await _assert_no_active_tool_calls(session, run.id)
            result = await session.execute(
''',
    '''            row = await _lock_owned_run(
                session, run_id=run.id, expected_generation=expected_generation
            )
            _assert_business_progression_allowed(row)
            await _assert_no_active_tool_calls(session, run.id)
            result = await session.execute(
''',
)

# Side-effect/READ proposal persistence guards were added above. Denied proposal
# is also a business consequence; block it under cancel.
replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''            run_row = await _lock_owned_run(
                session,
                run_id=run.id,
                expected_generation=expected_generation,
            )
            await _assert_no_active_tool_calls(session, run.id)
            await _assert_deadline_not_expired(session, run_row)
            state = await _lock_run_state(session, run.id)
''',
    '''            run_row = await _lock_owned_run(
                session,
                run_id=run.id,
                expected_generation=expected_generation,
            )
            _assert_business_progression_allowed(run_row)
            await _assert_no_active_tool_calls(session, run.id)
            await _assert_deadline_not_expired(session, run_row)
            state = await _lock_run_state(session, run.id)
''',
)


# ---------------------------------------------------------------------------
# Manual-review stopping state under cancellation is CANCELLED + MANUAL_REVIEW.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''            action_row.status = ExternalActionStatus.MANUAL_REVIEW
            action_row.updated_at = func.clock_timestamp()
            run_row.status = RunStatus.WAITING_ACTION_RESOLUTION
            run_row.queue_reason = None
            run_row.available_at = None
            run_row.owner_worker_id = None
            run_row.lease_expires_at = None
''',
    '''            action_row.status = ExternalActionStatus.MANUAL_REVIEW
            action_row.updated_at = func.clock_timestamp()
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
                run_row.completed_at = func.clock_timestamp()
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''        action.manual_review()
        run.wait_for_action_resolution()

    async def record_reconciliation_started(
''',
    '''        action.manual_review()
        if run.cancel_requested:
            run.cancel()
        else:
            run.wait_for_action_resolution()

    async def record_reconciliation_started(
''',
)

# D3 reconciliation-result MANUAL_REVIEW branch.
replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''                action_row.status = ExternalActionStatus.MANUAL_REVIEW
                action_row.updated_at = db_now
                run_row.status = RunStatus.WAITING_ACTION_RESOLUTION
                run_row.queue_reason = None
                run_row.available_at = None
                run_row.owner_worker_id = None
                run_row.lease_expires_at = None
''',
    '''                action_row.status = ExternalActionStatus.MANUAL_REVIEW
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

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''        else:
            action.manual_review()
            run.wait_for_action_resolution()
        return returned_message
''',
    '''        else:
            action.manual_review()
            if run.cancel_requested:
                run.cancel()
            else:
                run.wait_for_action_resolution()
        return returned_message
''',
)


# ---------------------------------------------------------------------------
# API exposes cancellation and durable cancellation intent.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/api/schemas.py",
    '''    failure_reason: str | None = None
    created_at: datetime
''',
    '''    failure_reason: str | None = None
    cancel_requested: bool = False
    created_at: datetime
''',
)

replace_once(
    "src/agentforge/api/app.py",
    '''        failure_reason=run.failure_reason,
        created_at=run.created_at,
''',
    '''        failure_reason=run.failure_reason,
        cancel_requested=run.cancel_requested,
        created_at=run.created_at,
''',
)

replace_once(
    "src/agentforge/api/app.py",
    '''    @app.get("/v1/runs/{run_id}", response_model=RunView)
    async def get_run(run_id: UUID) -> RunView:
''',
    '''    @app.post("/v1/runs/{run_id}/cancel", response_model=RunView)
    async def cancel_run(run_id: UUID) -> RunView:
        try:
            run = await store.cancel_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        return _run_view(run)

    @app.get("/v1/runs/{run_id}", response_model=RunView)
    async def get_run(run_id: UUID) -> RunView:
''',
)

# Fake API store support.
replace_once(
    "tests/unit/test_api_contract.py",
    '''    async def get_run(self, run_id):
        return self.runs.get(run_id)

    async def claim_next_run(self, *, worker_id: str, lease_seconds: int):
''',
    '''    async def get_run(self, run_id):
        return self.runs.get(run_id)

    async def cancel_run(self, run_id):
        run = self.runs.get(run_id)
        if run is None:
            raise KeyError(run_id)
        run.request_cancel()
        run.cancel()
        return run

    async def claim_next_run(self, *, worker_id: str, lease_seconds: int):
''',
)

append_text(
    "tests/unit/test_api_contract.py",
    "test_cancel_run_api_contract",
    r'''


def test_cancel_run_api_contract() -> None:
    store = FakeRuntimeStore()
    client = TestClient(create_app(store))
    created = client.post(
        "/v1/runs",
        json={"agent_version_id": str(store.agent_version_id), "input": "cancel me"},
        headers={"Idempotency-Key": "run-cancel-0001"},
    ).json()

    response = client.post(f"/v1/runs/{created['id']}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"
    assert response.json()["cancel_requested"] is True
'''
)


# ---------------------------------------------------------------------------
# E1 integration acceptance: immediate cancel, READY stabilization, and fence.
# ---------------------------------------------------------------------------
append_text(
    "tests/integration/test_postgres_runtime.py",
    "test_cancel_queued_run_terminalizes_without_business_work",
    r'''


@pytest.mark.asyncio
async def test_cancel_queued_run_terminalizes_without_business_work() -> None:
    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store = PostgresRuntimeStore(sessions)

    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="cancel before claim",
        idempotency_key="integration-e1-cancel-queued",
        principal_scope="test-user",
    )
    cancelled = await store.cancel_run(created.id)
    assert cancelled.status is RunStatus.CANCELLED
    assert cancelled.cancel_requested is True
    assert cancelled.completed_at is not None
    assert await store.claim_next_run(worker_id="must-not-claim", lease_seconds=30) is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_cancel_ready_side_effect_aborts_before_action_commit() -> None:
    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode
    from agentforge.infrastructure.db.models import ExternalActionRow

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)

    side_tool_id = uuid4()
    side_version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(ToolDefinitionRow(id=side_tool_id, name="cancel_ready_write", description="write"))
        await session.flush()
        session.add(
            ToolVersionRow(
                id=side_version_id,
                tool_id=side_tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.WRITE,
                implementation_ref="tests:cancel_ready_write",
                allow_no_approval_execution=True,
                reconciliation_mode=ReconciliationMode.NONE,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=DEMO_AGENT_VERSION_ID,
                tool_version_id=side_version_id,
                tool_alias="cancel_ready_write",
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
                name="cancel_ready_write",
                description="write",
                input_schema={"type": "object"},
                func=lambda invocation: {"must": "not execute"},
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="cancel ready action",
        idempotency_key="integration-e1-cancel-ready",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="e1-ready", lease_seconds=30)
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
        tool_name="cancel_ready_write",
        arguments={"v": 1},
    )
    prepared = ToolCoordinator(registry).prepare_side_effect(
        proposal=proposal,
        agent_version=await store.load_agent_version(DEMO_AGENT_VERSION_ID),
    )
    await recorder.record_model_side_effect_prepared(
        invocation,
        proposal,
        prepared.call,
        prepared.snapshot,
        prepared.action,
        expected_generation=claimed.execution_generation,
    )

    cancelled = await store.cancel_run(created.id)
    assert cancelled.status is RunStatus.CANCELLED
    assert cancelled.cancel_requested is True

    async with sessions() as session:
        action = (
            await session.execute(
                select(ExternalActionRow).where(ExternalActionRow.run_id == created.id)
            )
        ).scalar_one()
        call = await session.get(ToolCallRow, action.tool_call_id)
        started_attempts = await session.scalar(
            select(func.count())
            .select_from(ToolExecutionAttemptRow)
            .where(
                ToolExecutionAttemptRow.external_action_id == action.id,
                ToolExecutionAttemptRow.status == ToolExecutionAttemptStatus.STARTED,
            )
        )
    assert action.status is ExternalActionStatus.ABORTED
    assert action.current_attempt_id is None
    assert call is not None and call.status is ToolCallStatus.NOT_EXECUTED
    assert started_attempts == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_cancel_requested_fences_new_model_business_progression() -> None:
    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store = PostgresRuntimeStore(sessions)

    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="cancel fence",
        idempotency_key="integration-e1-cancel-fence",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="e1-fence", lease_seconds=30)
    assert claimed is not None

    # Keep an invocation STARTED so cancel_requested is durable but cannot yet
    # terminalize. A second business progression start must fail closed.
    recorder = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed.execution_generation,
    )
    await recorder.begin_model_invocation(
        run_id=created.id,
        invocation_id=uuid4(),
        expected_generation=claimed.execution_generation,
    )
    requested = await store.cancel_run(created.id)
    assert requested.status is RunStatus.RUNNING
    assert requested.cancel_requested is True

    with pytest.raises(BusinessProgressionBlockedError, match="CANCEL_REQUESTED"):
        await recorder.begin_model_invocation(
            run_id=created.id,
            invocation_id=uuid4(),
            expected_generation=claimed.execution_generation,
        )
    await engine.dispose()
'''
)
