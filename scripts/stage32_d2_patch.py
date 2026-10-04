from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}: {old[:140]!r}")
    file.write_text(text.replace(old, new))


def append_text(path: str, marker: str, block: str) -> None:
    file = Path(path)
    text = file.read_text()
    if marker in text:
        raise SystemExit(f"{path}: marker already present: {marker}")
    file.write_text(text + block)


# ---------------------------------------------------------------------------
# Explicit retryable side-effect signal: proof of non-execution is mandatory.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/application/errors.py",
    '''class ToolTransientError(ToolAdapterError):
    """Explicit opt-in signal for a retryable READ adapter failure."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            error_class="TRANSIENT",
            definite_not_executed=True,
        )


class BusinessProgressionBlockedError(RuntimeError):
''',
    '''class ToolTransientError(ToolAdapterError):
    """Explicit opt-in signal for a retryable READ adapter failure."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            error_class="TRANSIENT",
            definite_not_executed=True,
        )


class SideEffectTransientError(ToolAdapterError):
    """Explicit retry signal only when the adapter proves no external effect occurred."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            error_class="TRANSIENT",
            definite_not_executed=True,
        )


class BusinessProgressionBlockedError(RuntimeError):
''',
)


# ---------------------------------------------------------------------------
# Versioned side-effect retry policy.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/domain/models.py",
    '''    idempotency_supported: bool = False
    reconciliation_mode: ReconciliationMode = ReconciliationMode.NONE

    def __post_init__(self) -> None:
''',
    '''    idempotency_supported: bool = False
    reconciliation_mode: ReconciliationMode = ReconciliationMode.NONE
    side_effect_retry_max_attempts: int = 1
    side_effect_retry_initial_backoff_seconds: int = 1
    side_effect_retry_max_backoff_seconds: int = 30

    def __post_init__(self) -> None:
''',
)

replace_once(
    "src/agentforge/domain/models.py",
    '''        if self.effect_type is ToolEffectType.READ and self.allow_no_approval_execution:
            raise ValueError("READ tool cannot be marked for side-effect execution")

    @property
''',
    '''        if self.effect_type is ToolEffectType.READ and self.allow_no_approval_execution:
            raise ValueError("READ tool cannot be marked for side-effect execution")
        if self.side_effect_retry_max_attempts <= 0:
            raise ValueError("side_effect_retry_max_attempts must be positive")
        if self.side_effect_retry_initial_backoff_seconds < 0:
            raise ValueError("side-effect retry initial backoff cannot be negative")
        if (
            self.side_effect_retry_max_backoff_seconds
            < self.side_effect_retry_initial_backoff_seconds
        ):
            raise ValueError("side-effect retry max backoff cannot be below initial backoff")

    @property
''',
)

replace_once(
    "src/agentforge/domain/models.py",
    '''    def read_retry_delay_seconds(self, failed_attempt_number: int) -> int:
        if failed_attempt_number <= 0:
            raise ValueError("failed_attempt_number must be positive")
        delay: int = self.read_retry_initial_backoff_seconds * (2 ** (failed_attempt_number - 1))
        return min(delay, self.read_retry_max_backoff_seconds)


@dataclass(frozen=True, slots=True)
class AgentVersion:
''',
    '''    def read_retry_delay_seconds(self, failed_attempt_number: int) -> int:
        if failed_attempt_number <= 0:
            raise ValueError("failed_attempt_number must be positive")
        delay: int = self.read_retry_initial_backoff_seconds * (2 ** (failed_attempt_number - 1))
        return min(delay, self.read_retry_max_backoff_seconds)

    def side_effect_retry_delay_seconds(self, failed_attempt_number: int) -> int:
        if failed_attempt_number <= 0:
            raise ValueError("failed_attempt_number must be positive")
        delay: int = self.side_effect_retry_initial_backoff_seconds * (
            2 ** (failed_attempt_number - 1)
        )
        return min(delay, self.side_effect_retry_max_backoff_seconds)


@dataclass(frozen=True, slots=True)
class AgentVersion:
''',
)

replace_once(
    "src/agentforge/domain/actions.py",
    '''    def fail_definite_not_executed(self) -> None:
        if self.status is not ExternalActionStatus.EXECUTING or self.current_attempt_id is None:
            raise ValueError("external action can only fail from EXECUTING")
        self.status = ExternalActionStatus.FAILED
        self.current_attempt_id = None

    def abort(self) -> None:
''',
    '''    def fail_definite_not_executed(self) -> None:
        if self.status is not ExternalActionStatus.EXECUTING or self.current_attempt_id is None:
            raise ValueError("external action can only fail from EXECUTING")
        self.status = ExternalActionStatus.FAILED
        self.current_attempt_id = None

    def retry_ready_after_definite_not_executed(self) -> None:
        if self.status is not ExternalActionStatus.EXECUTING or self.current_attempt_id is None:
            raise ValueError("external action can only retry from EXECUTING")
        self.status = ExternalActionStatus.READY
        self.current_attempt_id = None

    def abort_after_definite_not_executed(self) -> None:
        if self.status is not ExternalActionStatus.EXECUTING or self.current_attempt_id is None:
            raise ValueError("external action can only abort an executing proven-no-effect attempt")
        self.status = ExternalActionStatus.ABORTED
        self.current_attempt_id = None

    def abort(self) -> None:
''',
)

replace_once(
    "src/agentforge/domain/models.py",
    '''    def unresolve(self, reason: str) -> None:
        if self.status is not ToolCallStatus.EXECUTING:
            raise ValueError("tool call can only become UNRESOLVED from EXECUTING")
        self.status = ToolCallStatus.UNRESOLVED
        self.error = reason

    def retry_after_failure(self, reason: str) -> None:
''',
    '''    def unresolve(self, reason: str) -> None:
        if self.status is not ToolCallStatus.EXECUTING:
            raise ValueError("tool call can only become UNRESOLVED from EXECUTING")
        self.status = ToolCallStatus.UNRESOLVED
        self.error = reason

    def abort_after_definite_not_executed(self, reason: str) -> None:
        if self.status is not ToolCallStatus.EXECUTING:
            raise ValueError("tool call can only abort an executing proven-no-effect attempt")
        self.status = ToolCallStatus.NOT_EXECUTED
        self.error = reason

    def retry_after_failure(self, reason: str) -> None:
''',
)

replace_once(
    "src/agentforge/domain/enums.py",
    '''    ACTION_UNKNOWN = "ACTION_UNKNOWN"
    ACTION_FAILED = "ACTION_FAILED"
    ACTION_ABORTED = "ACTION_ABORTED"
''',
    '''    ACTION_UNKNOWN = "ACTION_UNKNOWN"
    ACTION_FAILED = "ACTION_FAILED"
    ACTION_RETRY_READY = "ACTION_RETRY_READY"
    ACTION_ABORTED = "ACTION_ABORTED"
''',
)


# ---------------------------------------------------------------------------
# Persistence model + migration for versioned side-effect retry policy.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/infrastructure/db/models.py",
    '''        CheckConstraint(
            "effect_type <> 'READ' OR NOT allow_no_approval_execution",
            name="ck_tool_versions_read_not_side_effect_executable",
        ),
    )
''',
    '''        CheckConstraint(
            "effect_type <> 'READ' OR NOT allow_no_approval_execution",
            name="ck_tool_versions_read_not_side_effect_executable",
        ),
        CheckConstraint(
            "side_effect_retry_max_attempts > 0",
            name="ck_tool_versions_positive_side_effect_retry_attempts",
        ),
        CheckConstraint(
            "side_effect_retry_initial_backoff_seconds >= 0",
            name="ck_tool_versions_nonnegative_side_effect_retry_initial_backoff",
        ),
        CheckConstraint(
            "side_effect_retry_max_backoff_seconds >= side_effect_retry_initial_backoff_seconds",
            name="ck_tool_versions_side_effect_retry_backoff_order",
        ),
    )
''',
)

replace_once(
    "src/agentforge/infrastructure/db/models.py",
    '''    read_retry_max_backoff_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    created_at: Mapped[datetime] = mapped_column(
''',
    '''    read_retry_max_backoff_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    side_effect_retry_max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    side_effect_retry_initial_backoff_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    side_effect_retry_max_backoff_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30
    )
    created_at: Mapped[datetime] = mapped_column(
''',
)

Path("migrations/versions/0012_side_effect_retry.py").write_text(
    '''"""add versioned side-effect safe retry policy

Revision ID: 0012_side_effect_retry
Revises: 0011_side_effect_unknown
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_side_effect_retry"
down_revision: str | None = "0011_side_effect_unknown"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tool_versions",
        sa.Column(
            "side_effect_retry_max_attempts",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "tool_versions",
        sa.Column(
            "side_effect_retry_initial_backoff_seconds",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "tool_versions",
        sa.Column(
            "side_effect_retry_max_backoff_seconds",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
    )
    op.create_check_constraint(
        "ck_tool_versions_positive_side_effect_retry_attempts",
        "tool_versions",
        "side_effect_retry_max_attempts > 0",
    )
    op.create_check_constraint(
        "ck_tool_versions_nonnegative_side_effect_retry_initial_backoff",
        "tool_versions",
        "side_effect_retry_initial_backoff_seconds >= 0",
    )
    op.create_check_constraint(
        "ck_tool_versions_side_effect_retry_backoff_order",
        "tool_versions",
        "side_effect_retry_max_backoff_seconds >= side_effect_retry_initial_backoff_seconds",
    )
    op.alter_column("tool_versions", "side_effect_retry_max_attempts", server_default=None)
    op.alter_column(
        "tool_versions",
        "side_effect_retry_initial_backoff_seconds",
        server_default=None,
    )
    op.alter_column(
        "tool_versions",
        "side_effect_retry_max_backoff_seconds",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_tool_versions_side_effect_retry_backoff_order",
        "tool_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_tool_versions_nonnegative_side_effect_retry_initial_backoff",
        "tool_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_tool_versions_positive_side_effect_retry_attempts",
        "tool_versions",
        type_="check",
    )
    op.drop_column("tool_versions", "side_effect_retry_max_backoff_seconds")
    op.drop_column("tool_versions", "side_effect_retry_initial_backoff_seconds")
    op.drop_column("tool_versions", "side_effect_retry_max_attempts")
'''
)


# ---------------------------------------------------------------------------
# Mapping durable ToolVersion policy into immutable ToolBinding.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/infrastructure/db/mappers.py",
    '''            bool,
            ReconciliationMode,
        ]
''',
    '''            bool,
            ReconciliationMode,
            int,
            int,
            int,
        ]
''',
)

replace_once(
    "src/agentforge/infrastructure/db/mappers.py",
    '''                reconciliation_mode=reconciliation_mode,
            )
            for (
''',
    '''                reconciliation_mode=reconciliation_mode,
                side_effect_retry_max_attempts=side_effect_retry_max_attempts,
                side_effect_retry_initial_backoff_seconds=side_effect_retry_initial_backoff_seconds,
                side_effect_retry_max_backoff_seconds=side_effect_retry_max_backoff_seconds,
            )
            for (
''',
)

replace_once(
    "src/agentforge/infrastructure/db/mappers.py",
    '''                idempotency_supported,
                reconciliation_mode,
            ) in bindings
''',
    '''                idempotency_supported,
                reconciliation_mode,
                side_effect_retry_max_attempts,
                side_effect_retry_initial_backoff_seconds,
                side_effect_retry_max_backoff_seconds,
            ) in bindings
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''                        ToolVersionRow.idempotency_supported,
                        ToolVersionRow.reconciliation_mode,
                    )
''',
    '''                        ToolVersionRow.idempotency_supported,
                        ToolVersionRow.reconciliation_mode,
                        ToolVersionRow.side_effect_retry_max_attempts,
                        ToolVersionRow.side_effect_retry_initial_backoff_seconds,
                        ToolVersionRow.side_effect_retry_max_backoff_seconds,
                    )
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''                        idempotency_supported,
                        reconciliation_mode,
                    )
                    for (
''',
    '''                        idempotency_supported,
                        reconciliation_mode,
                        side_effect_retry_max_attempts,
                        side_effect_retry_initial_backoff_seconds,
                        side_effect_retry_max_backoff_seconds,
                    )
                    for (
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''                        idempotency_supported,
                        reconciliation_mode,
                    ) in rows
''',
    '''                        idempotency_supported,
                        reconciliation_mode,
                        side_effect_retry_max_attempts,
                        side_effect_retry_initial_backoff_seconds,
                        side_effect_retry_max_backoff_seconds,
                    ) in rows
''',
)


# ---------------------------------------------------------------------------
# Recorder protocol for safe side-effect retry.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/application/ports.py",
    '''    async def record_side_effect_definite_failure_and_fail_run(
        self,
        call: ToolCall,
        action: ExternalAction,
        attempt: ToolExecutionAttempt,
        run: Run,
        *,
        error: str,
        error_class: str,
        expected_generation: int,
    ) -> None: ...

    async def record_recovered_read_started(
''',
    '''    async def record_side_effect_definite_failure_and_fail_run(
        self,
        call: ToolCall,
        action: ExternalAction,
        attempt: ToolExecutionAttempt,
        run: Run,
        *,
        error: str,
        error_class: str,
        expected_generation: int,
    ) -> None: ...

    async def record_side_effect_transient_failure(
        self,
        call: ToolCall,
        action: ExternalAction,
        attempt: ToolExecutionAttempt,
        run: Run,
        *,
        max_attempts: int,
        initial_backoff_seconds: int,
        max_backoff_seconds: int,
        expected_generation: int,
    ) -> bool: ...

    async def record_recovered_read_started(
''',
)


# ---------------------------------------------------------------------------
# In-memory safe retry persistence.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/application/run_manager.py",
    '''    async def record_recovered_read_started(
        self,
        call: ToolCall,
        *,
        expected_generation: int,
    ) -> None:
''',
    '''    async def record_side_effect_transient_failure(
        self,
        call: ToolCall,
        action: ExternalAction,
        attempt: ToolExecutionAttempt,
        run: Run,
        *,
        max_attempts: int,
        initial_backoff_seconds: int,
        max_backoff_seconds: int,
        expected_generation: int,
    ) -> bool:
        if call.status is not ToolCallStatus.EXECUTING:
            raise ValueError("side-effect retry requires EXECUTING ToolCall")
        if action.status is not ExternalActionStatus.EXECUTING:
            raise ValueError("side-effect retry requires EXECUTING ExternalAction")
        if action.current_attempt_id != attempt.id:
            raise ValueError("side-effect retry attempt is not current")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if initial_backoff_seconds < 0 or max_backoff_seconds < initial_backoff_seconds:
            raise ValueError("invalid side-effect retry backoff")
        durable_attempt = self._started_tool_attempt(call.id)
        if durable_attempt.id != attempt.id:
            raise RuntimeError("side-effect retry durable attempt mismatch")
        error = "retryable side-effect failure with proven non-execution"
        durable_attempt.fail(
            error,
            error_class="TRANSIENT",
            definite_not_executed=True,
            outcome_reason="SIDE_EFFECT_TRANSIENT_DEFINITE_NOT_EXECUTED",
        )
        assert self.run_state is not None
        delay_seconds = min(
            initial_backoff_seconds * (2 ** (attempt.attempt_number - 1)),
            max_backoff_seconds,
        )
        due_at = utcnow() + timedelta(seconds=delay_seconds)
        retry_allowed = (
            attempt.attempt_number < max_attempts
            and self.run_state.tool_attempts_used < run.max_tool_attempts
            and due_at < run.deadline_at
        )
        if retry_allowed:
            call.retry_ready(error)
            action.retry_ready_after_definite_not_executed()
            run.yield_to_queue(QueueReason.RETRY)
            run.available_at = due_at
            self._append_event(
                run,
                EventType.TOOL_FAILED,
                {
                    "tool_call_id": str(call.id),
                    "attempt_id": str(attempt.id),
                    "attempt_number": attempt.attempt_number,
                    "error_class": "TRANSIENT",
                    "definite_not_executed": True,
                },
            )
            self._append_event(
                run,
                EventType.ACTION_RETRY_READY,
                {
                    "external_action_id": str(action.id),
                    "operation_id": str(action.operation_id),
                    "attempt_id": str(attempt.id),
                },
            )
            self._append_event(
                run,
                EventType.TOOL_RETRY_SCHEDULED,
                {
                    "tool_call_id": str(call.id),
                    "attempt_number": attempt.attempt_number,
                    "delay_seconds": delay_seconds,
                },
            )
            return True

        if attempt.attempt_number >= max_attempts:
            reason = "SIDE_EFFECT_RETRY_EXHAUSTED: versioned safe retry attempts exhausted"
            call.fail(error)
            action.fail_definite_not_executed()
            run.fail(reason)
            self._append_event(
                run,
                EventType.ACTION_FAILED,
                {
                    "external_action_id": str(action.id),
                    "operation_id": str(action.operation_id),
                    "reason": reason,
                },
            )
        else:
            reason = (
                "BUDGET_EXCEEDED: max_tool_attempts exhausted"
                if self.run_state.tool_attempts_used >= run.max_tool_attempts
                else "DEADLINE_EXCEEDED: side-effect retry due time reaches run deadline"
            )
            call.abort_after_definite_not_executed(reason)
            action.abort_after_definite_not_executed()
            run.fail(reason)
            self._append_event(
                run,
                EventType.ACTION_ABORTED,
                {
                    "external_action_id": str(action.id),
                    "operation_id": str(action.operation_id),
                    "reason": reason,
                },
            )
        self._append_event(run, EventType.RUN_FAILED, {"reason": run.failure_reason})
        return False

    async def record_recovered_read_started(
        self,
        call: ToolCall,
        *,
        expected_generation: int,
    ) -> None:
''',
)


# ---------------------------------------------------------------------------
# RunManager catches explicit safe retry before generic definite failure.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/application/run_manager.py",
    '''    RunExecutionFailedError,
    ToolAdapterError,
    ToolTransientError,
)
''',
    '''    RunExecutionFailedError,
    SideEffectTransientError,
    ToolAdapterError,
    ToolTransientError,
)
''',
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''        try:
            call = await self._tools.execute_side_effect(prepared, attempt)
        except ToolAdapterError as exc:
''',
    '''        try:
            call = await self._tools.execute_side_effect(prepared, attempt)
        except SideEffectTransientError as exc:
            scheduled = await recorder.record_side_effect_transient_failure(
                prepared.call,
                prepared.action,
                attempt,
                run,
                max_attempts=prepared.binding.side_effect_retry_max_attempts,
                initial_backoff_seconds=prepared.binding.side_effect_retry_initial_backoff_seconds,
                max_backoff_seconds=prepared.binding.side_effect_retry_max_backoff_seconds,
                expected_generation=expected_generation,
            )
            if scheduled:
                return None
            raise RunExecutionFailedError(run.failure_reason or str(exc)) from exc
        except ToolAdapterError as exc:
''',
)


# ---------------------------------------------------------------------------
# PostgreSQL safe retry persistence.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''    async def record_recovered_read_started(
        self,
        call: ToolCall,
        *,
        expected_generation: int,
    ) -> None:
''',
    '''    async def record_side_effect_transient_failure(
        self,
        call: ToolCall,
        action: ExternalAction,
        attempt: ToolExecutionAttempt,
        run: Run,
        *,
        max_attempts: int,
        initial_backoff_seconds: int,
        max_backoff_seconds: int,
        expected_generation: int,
    ) -> bool:
        """Retry only after explicit proof that the physical effect did not occur."""
        self._assert_generation(expected_generation)
        if call.status is not ToolCallStatus.EXECUTING:
            raise ValueError("side-effect retry requires EXECUTING ToolCall")
        if action.status is not ExternalActionStatus.EXECUTING:
            raise ValueError("side-effect retry requires EXECUTING ExternalAction")
        if action.current_attempt_id != attempt.id:
            raise ValueError("side-effect retry attempt is not current")
        if run.status is not RunStatus.RUNNING:
            raise ValueError("side-effect retry requires RUNNING Run")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if initial_backoff_seconds < 0 or max_backoff_seconds < initial_backoff_seconds:
            raise ValueError("invalid side-effect retry backoff")

        async with self._sessions() as session, session.begin():
            run_row = await _lock_owned_run(
                session,
                run_id=run.id,
                expected_generation=expected_generation,
            )
            action_row = (
                await session.execute(
                    select(ExternalActionRow)
                    .where(
                        ExternalActionRow.id == action.id,
                        ExternalActionRow.run_id == run.id,
                    )
                    .with_for_update()
                )
            ).scalar_one()
            call_row = (
                await session.execute(
                    select(ToolCallRow)
                    .where(
                        ToolCallRow.id == call.id,
                        ToolCallRow.run_id == run.id,
                    )
                    .with_for_update()
                )
            ).scalar_one()
            attempt_row = (
                await session.execute(
                    select(ToolExecutionAttemptRow)
                    .where(
                        ToolExecutionAttemptRow.id == attempt.id,
                        ToolExecutionAttemptRow.tool_call_id == call.id,
                        ToolExecutionAttemptRow.external_action_id == action.id,
                    )
                    .with_for_update()
                )
            ).scalar_one()
            if (
                action_row.status is not ExternalActionStatus.EXECUTING
                or action_row.current_attempt_id != attempt.id
                or call_row.status is not ToolCallStatus.EXECUTING
                or attempt_row.status is not ToolExecutionAttemptStatus.STARTED
            ):
                raise RuntimeError("side-effect retry lost current-attempt authorization")

            state = await _lock_run_state(session, run.id)
            db_now = await _database_now(session)
            delay_seconds = min(
                initial_backoff_seconds * (2 ** (attempt_row.attempt_number - 1)),
                max_backoff_seconds,
            )
            due_at = db_now + timedelta(seconds=delay_seconds)
            error = "retryable side-effect failure with proven non-execution"

            attempt_row.status = ToolExecutionAttemptStatus.FAILED
            attempt_row.error = error
            attempt_row.error_class = "TRANSIENT"
            attempt_row.definite_not_executed = True
            attempt_row.outcome_reason = "SIDE_EFFECT_TRANSIENT_DEFINITE_NOT_EXECUTED"
            attempt_row.finished_at = db_now

            retry_allowed = (
                attempt_row.attempt_number < max_attempts
                and state.tool_attempts_used < run_row.max_tool_attempts
                and due_at < run_row.deadline_at
            )
            if retry_allowed:
                call_row.status = ToolCallStatus.READY
                call_row.error = error
                action_row.status = ExternalActionStatus.READY
                action_row.current_attempt_id = None
                action_row.updated_at = db_now
                run_row.status = RunStatus.QUEUED
                run_row.queue_reason = QueueReason.RETRY
                run_row.available_at = due_at
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
                            event_type=EventType.ACTION_RETRY_READY.value,
                            payload={
                                "external_action_id": str(action.id),
                                "operation_id": str(action.operation_id),
                                "attempt_id": str(attempt.id),
                            },
                        ),
                        DomainEventRow(
                            id=uuid4(),
                            run_id=run.id,
                            sequence=seqs[2],
                            event_type=EventType.TOOL_RETRY_SCHEDULED.value,
                            payload={
                                "tool_call_id": str(call.id),
                                "attempt_number": attempt.attempt_number,
                                "delay_seconds": delay_seconds,
                            },
                        ),
                    ]
                )
                attempt.fail(
                    error,
                    error_class="TRANSIENT",
                    definite_not_executed=True,
                    outcome_reason="SIDE_EFFECT_TRANSIENT_DEFINITE_NOT_EXECUTED",
                )
                call.retry_ready(error)
                action.retry_ready_after_definite_not_executed()
                run.status = RunStatus.QUEUED
                run.queue_reason = QueueReason.RETRY
                run.available_at = due_at
                run.owner_worker_id = None
                run.lease_expires_at = None
                return True

            if attempt_row.attempt_number >= max_attempts:
                reason = "SIDE_EFFECT_RETRY_EXHAUSTED: versioned safe retry attempts exhausted"
                call_row.status = ToolCallStatus.FAILED
                call_row.error = error
                action_row.status = ExternalActionStatus.FAILED
                event_type = EventType.ACTION_FAILED
            elif state.tool_attempts_used >= run_row.max_tool_attempts:
                reason = "BUDGET_EXCEEDED: max_tool_attempts exhausted"
                call_row.status = ToolCallStatus.NOT_EXECUTED
                call_row.error = reason
                action_row.status = ExternalActionStatus.ABORTED
                event_type = EventType.ACTION_ABORTED
            else:
                reason = "DEADLINE_EXCEEDED: side-effect retry due time reaches run deadline"
                call_row.status = ToolCallStatus.NOT_EXECUTED
                call_row.error = reason
                action_row.status = ExternalActionStatus.ABORTED
                event_type = EventType.ACTION_ABORTED
            action_row.current_attempt_id = None
            action_row.updated_at = db_now
            run_row.status = RunStatus.FAILED
            run_row.failure_reason = reason
            run_row.completed_at = db_now
            run_row.owner_worker_id = None
            run_row.lease_expires_at = None
            seqs = list(await _allocate_event_sequences(session, run.id, 2))
            session.add_all(
                [
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[0],
                        event_type=event_type.value,
                        payload={
                            "external_action_id": str(action.id),
                            "operation_id": str(action.operation_id),
                            "reason": reason,
                        },
                    ),
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[1],
                        event_type=EventType.RUN_FAILED.value,
                        payload={"reason": reason},
                    ),
                ]
            )
            attempt.fail(
                error,
                error_class="TRANSIENT",
                definite_not_executed=True,
                outcome_reason="SIDE_EFFECT_TRANSIENT_DEFINITE_NOT_EXECUTED",
            )
            if event_type is EventType.ACTION_FAILED:
                call.fail(error)
                action.fail_definite_not_executed()
            else:
                call.abort_after_definite_not_executed(reason)
                action.abort_after_definite_not_executed()
            run.status = RunStatus.FAILED
            run.failure_reason = reason
            run.completed_at = db_now
            return False

    async def record_recovered_read_started(
        self,
        call: ToolCall,
        *,
        expected_generation: int,
    ) -> None:
''',
)


# ---------------------------------------------------------------------------
# Takeover: orphaned side-effect STARTED is UNKNOWN before any retry/reasoning.
# ---------------------------------------------------------------------------
replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''    EventType,
    MessageRole,
''',
    '''    EventType,
    ExternalActionStatus,
    MessageRole,
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''    DomainEventRow,
    IdempotencyRecordRow,
''',
    '''    DomainEventRow,
    ExternalActionRow,
    IdempotencyRecordRow,
''',
)

insert_anchor = '''async def _prepare_orphaned_read_calls_for_retry(session: AsyncSession, run_id: UUID) -> list[UUID]:
'''
if insert_anchor not in Path("src/agentforge/infrastructure/db/runtime_store.py").read_text():
    raise SystemExit("runtime_store orphan read anchor missing")
replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    insert_anchor,
    '''async def _recover_orphaned_side_effect_attempts(
    session: AsyncSession, run_id: UUID
) -> list[tuple[UUID, UUID, UUID]]:
    """Close stale side-effect authorization as UNKNOWN under Run lock.

    claim_next_run already owns the Run row lock. This helper then obeys:
    ExternalAction -> ToolCall -> ToolExecutionAttempt.
    """
    actions = (
        (
            await session.execute(
                select(ExternalActionRow)
                .where(
                    ExternalActionRow.run_id == run_id,
                    ExternalActionRow.status == ExternalActionStatus.EXECUTING,
                )
                .order_by(ExternalActionRow.id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    recovered: list[tuple[UUID, UUID, UUID]] = []
    for action in actions:
        if action.current_attempt_id is None:
            raise RuntimeError("EXECUTING ExternalAction lost current_attempt_id")
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
        attempt = (
            await session.execute(
                select(ToolExecutionAttemptRow)
                .where(
                    ToolExecutionAttemptRow.id == action.current_attempt_id,
                    ToolExecutionAttemptRow.tool_call_id == call.id,
                    ToolExecutionAttemptRow.external_action_id == action.id,
                )
                .with_for_update()
            )
        ).scalar_one()
        if call.status is not ToolCallStatus.EXECUTING:
            raise RuntimeError("EXECUTING ExternalAction does not project to EXECUTING ToolCall")
        if attempt.status is not ToolExecutionAttemptStatus.STARTED:
            raise RuntimeError("current side-effect attempt is not STARTED")

        attempt.status = ToolExecutionAttemptStatus.UNKNOWN
        attempt.definite_not_executed = False
        attempt.outcome_reason = "LEASE_LOST_RESULT_NOT_DURABLE"
        attempt.finished_at = func.clock_timestamp()
        action.status = ExternalActionStatus.UNKNOWN
        action.current_attempt_id = None
        action.updated_at = func.clock_timestamp()
        call.status = ToolCallStatus.UNRESOLVED
        call.error = "previous executor lease expired with external truth unresolved"
        recovered.append((action.id, call.id, attempt.id))
    return recovered


async def _prepare_orphaned_read_calls_for_retry(session: AsyncSession, run_id: UUID) -> list[UUID]:
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''            recovered_call_ids = (
                await _prepare_orphaned_read_calls_for_retry(session, row.id)
                if was_recovery
                else []
            )
            base_event_count = 1 if was_recovery else 2
''',
    '''            recovered_side_effects = (
                await _recover_orphaned_side_effect_attempts(session, row.id)
                if was_recovery
                else []
            )
            recovered_call_ids = (
                await _prepare_orphaned_read_calls_for_retry(session, row.id)
                if was_recovery
                else []
            )
            base_event_count = 1 if was_recovery else 2
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''                    base_event_count + len(recovered_model_ids) + len(recovered_call_ids),
''',
    '''                    base_event_count
                    + len(recovered_model_ids)
                    + len(recovered_side_effects)
                    + len(recovered_call_ids),
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''            for tool_call_id in recovered_call_ids:
                session.add(
''',
    '''            for external_action_id, tool_call_id, attempt_id in recovered_side_effects:
                session.add(
                    DomainEventRow(
                        id=uuid4(),
                        run_id=row.id,
                        sequence=sequences[offset],
                        event_type=EventType.ACTION_UNKNOWN.value,
                        payload={
                            "external_action_id": str(external_action_id),
                            "tool_call_id": str(tool_call_id),
                            "attempt_id": str(attempt_id),
                            "reason": "LEASE_LOST_RESULT_NOT_DURABLE",
                        },
                    )
                )
                offset += 1
            for tool_call_id in recovered_call_ids:
                session.add(
''',
)


# ---------------------------------------------------------------------------
# Unit tests.
# ---------------------------------------------------------------------------
replace_once(
    "tests/unit/test_run_manager.py",
    '''    RunExecutionFailedError,
    ToolAdapterError,
    ToolTransientError,
)
''',
    '''    RunExecutionFailedError,
    SideEffectTransientError,
    ToolAdapterError,
    ToolTransientError,
)
''',
)

append_text(
    "tests/unit/test_run_manager.py",
    "test_safe_side_effect_retry_reuses_operation_id_and_next_attempt_number",
    r'''


@pytest.mark.asyncio
async def test_safe_side_effect_retry_reuses_operation_id_and_next_attempt_number() -> None:
    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode, ToolEffectType

    version_id = uuid4()
    operation_ids = []
    calls = 0

    async def flaky(invocation):
        nonlocal calls
        calls += 1
        operation_ids.append(invocation.operation_id)
        if calls == 1:
            raise SideEffectTransientError("connection failed before request bytes were sent")
        return {"resource": "R-1"}

    registry = InMemoryToolRegistry(
        [
            SideEffectFunctionTool(
                version_id=version_id,
                name="safe_retry_write",
                description="write",
                input_schema={"type": "object"},
                func=flaky,
            )
        ]
    )
    model = ScriptedFakeModel(
        [
            ToolStep("safe_retry_write", {"value": "same"}),
            FinalStep("done"),
        ]
    )
    manager = RunManager(NativeRunner(model, registry), ToolCoordinator(registry))
    av = AgentVersion(
        uuid4(),
        uuid4(),
        1,
        "safe retry",
        (
            ToolBinding(
                version_id,
                "safe_retry_write",
                effect_type=ToolEffectType.WRITE,
                allow_no_approval_execution=True,
                reconciliation_mode=ReconciliationMode.NONE,
                side_effect_retry_max_attempts=2,
                side_effect_retry_initial_backoff_seconds=0,
                side_effect_retry_max_backoff_seconds=0,
            ),
        ),
    )
    run = Run(uuid4(), av.id, "write")
    run.queue()
    state = RunState(run.id)
    journal = ExecutionJournal()

    first = await manager.execute(
        run=run,
        run_state=state,
        agent_version=av,
        recorder=journal,
    )
    assert first is None
    assert run.status is RunStatus.QUEUED
    assert run.queue_reason is QueueReason.RETRY
    assert journal.external_actions[0].status is ExternalActionStatus.READY
    assert journal.external_actions[0].current_attempt_id is None
    assert journal.tool_calls[0].status is ToolCallStatus.READY
    assert journal.tool_attempts[0].status is ToolExecutionAttemptStatus.FAILED
    assert journal.tool_attempts[0].definite_not_executed is True

    second = await manager.execute(
        run=run,
        run_state=state,
        agent_version=av,
        recorder=journal,
    )
    assert second == "done"
    assert calls == 2
    assert operation_ids[0] == operation_ids[1]
    assert len(journal.tool_attempts) == 2
    assert [a.attempt_number for a in journal.tool_attempts] == [1, 2]
    assert journal.external_actions[0].status is ExternalActionStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_safe_side_effect_retry_exhaustion_fails_without_unknown() -> None:
    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode, ToolEffectType

    version_id = uuid4()

    async def always_no_effect(_invocation):
        raise SideEffectTransientError("preflight transport unavailable")

    registry = InMemoryToolRegistry(
        [
            SideEffectFunctionTool(
                version_id=version_id,
                name="retry_exhausted_write",
                description="write",
                input_schema={"type": "object"},
                func=always_no_effect,
            )
        ]
    )
    manager = RunManager(
        NativeRunner(
            ScriptedFakeModel([ToolStep("retry_exhausted_write", {})]),
            registry,
        ),
        ToolCoordinator(registry),
    )
    av = AgentVersion(
        uuid4(),
        uuid4(),
        1,
        "retry exhausted",
        (
            ToolBinding(
                version_id,
                "retry_exhausted_write",
                effect_type=ToolEffectType.WRITE,
                allow_no_approval_execution=True,
                reconciliation_mode=ReconciliationMode.NONE,
                side_effect_retry_max_attempts=1,
                side_effect_retry_initial_backoff_seconds=0,
                side_effect_retry_max_backoff_seconds=0,
            ),
        ),
    )
    run = Run(uuid4(), av.id, "write")
    run.queue()
    state = RunState(run.id)
    journal = ExecutionJournal()

    with pytest.raises(RunExecutionFailedError, match="SIDE_EFFECT_RETRY_EXHAUSTED"):
        await manager.execute(
            run=run,
            run_state=state,
            agent_version=av,
            recorder=journal,
        )

    assert run.status is RunStatus.FAILED
    assert journal.external_actions[0].status is ExternalActionStatus.FAILED
    assert journal.tool_calls[0].status is ToolCallStatus.FAILED
    assert journal.tool_attempts[0].status is ToolExecutionAttemptStatus.FAILED
    assert journal.tool_attempts[0].definite_not_executed is True
'''
)


# ---------------------------------------------------------------------------
# PostgreSQL integration tests for durable retry and orphan takeover.
# ---------------------------------------------------------------------------
replace_once(
    "tests/integration/test_postgres_runtime.py",
    '''    RunExecutionFailedError,
    StaleExecutorError,
    ToolAdapterError,
    ToolTransientError,
)
''',
    '''    RunExecutionFailedError,
    SideEffectTransientError,
    StaleExecutorError,
    ToolAdapterError,
    ToolTransientError,
)
''',
)

append_text(
    "tests/integration/test_postgres_runtime.py",
    "test_side_effect_safe_retry_reuses_action_and_operation_id_across_claims",
    r'''


@pytest.mark.asyncio
async def test_side_effect_safe_retry_reuses_action_and_operation_id_across_claims() -> None:
    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode
    from agentforge.infrastructure.db.models import ExternalActionRow

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)

    side_tool_id = uuid4()
    side_version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(ToolDefinitionRow(id=side_tool_id, name="safe_retry_db", description="write"))
        await session.flush()
        session.add(
            ToolVersionRow(
                id=side_version_id,
                tool_id=side_tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.WRITE,
                implementation_ref="tests:safe_retry_db",
                allow_no_approval_execution=True,
                reconciliation_mode=ReconciliationMode.NONE,
                side_effect_retry_max_attempts=2,
                side_effect_retry_initial_backoff_seconds=0,
                side_effect_retry_max_backoff_seconds=0,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=DEMO_AGENT_VERSION_ID,
                tool_version_id=side_version_id,
                tool_alias="safe_retry_db",
            )
        )

    operation_ids = []
    calls = 0

    async def flaky(invocation):
        nonlocal calls
        calls += 1
        operation_ids.append(invocation.operation_id)
        if calls == 1:
            raise SideEffectTransientError("request was not sent")
        return {"resource": "R-safe"}

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
                name="safe_retry_db",
                description="write",
                input_schema={"type": "object"},
                func=flaky,
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="safe retry db",
        idempotency_key="integration-d2-safe-retry",
        principal_scope="test-user",
    )

    claimed1 = await store.claim_next_run(worker_id="d2-a", lease_seconds=30)
    assert claimed1 is not None
    manager1 = RunManager(
        NativeRunner(ScriptedFakeModel([ToolStep("safe_retry_db", {"v": 1})]), registry),
        ToolCoordinator(registry),
    )
    recorder1 = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed1.execution_generation,
    )
    assert (
        await manager1.execute(
            run=claimed1,
            run_state=await store.load_run_state(created.id),
            agent_version=await store.load_agent_version(DEMO_AGENT_VERSION_ID),
            recorder=recorder1,
        )
        is None
    )
    after_first = await store.get_run(created.id)
    assert after_first is not None
    assert after_first.status is RunStatus.QUEUED
    assert after_first.queue_reason is QueueReason.RETRY

    async with sessions() as session:
        action1 = (
            await session.execute(
                select(ExternalActionRow).where(ExternalActionRow.run_id == created.id)
            )
        ).scalar_one()
        original_action_id = action1.id
        original_operation_id = action1.operation_id
        assert action1.status is ExternalActionStatus.READY
        attempts1 = (
            (
                await session.execute(
                    select(ToolExecutionAttemptRow)
                    .where(ToolExecutionAttemptRow.external_action_id == action1.id)
                    .order_by(ToolExecutionAttemptRow.attempt_number)
                )
            )
            .scalars()
            .all()
        )
        assert [a.attempt_number for a in attempts1] == [1]
        assert attempts1[0].status is ToolExecutionAttemptStatus.FAILED
        assert attempts1[0].definite_not_executed is True

    claimed2 = await store.claim_next_run(worker_id="d2-b", lease_seconds=30)
    assert claimed2 is not None
    assert claimed2.execution_generation == 2
    manager2 = RunManager(
        NativeRunner(ScriptedFakeModel([FinalStep("safe retry done")]), registry),
        ToolCoordinator(registry),
    )
    recorder2 = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed2.execution_generation,
    )
    assert (
        await manager2.execute(
            run=claimed2,
            run_state=await store.load_run_state(created.id),
            agent_version=await store.load_agent_version(DEMO_AGENT_VERSION_ID),
            recorder=recorder2,
        )
        == "safe retry done"
    )

    assert calls == 2
    assert operation_ids == [original_operation_id, original_operation_id]
    async with sessions() as session:
        action2 = (
            await session.execute(
                select(ExternalActionRow).where(ExternalActionRow.run_id == created.id)
            )
        ).scalar_one()
        attempts2 = (
            (
                await session.execute(
                    select(ToolExecutionAttemptRow)
                    .where(ToolExecutionAttemptRow.external_action_id == action2.id)
                    .order_by(ToolExecutionAttemptRow.attempt_number)
                )
            )
            .scalars()
            .all()
        )
    assert action2.id == original_action_id
    assert action2.operation_id == original_operation_id
    assert action2.status is ExternalActionStatus.SUCCEEDED
    assert [a.attempt_number for a in attempts2] == [1, 2]
    assert attempts2[1].status is ToolExecutionAttemptStatus.SUCCEEDED
    await engine.dispose()


@pytest.mark.asyncio
async def test_orphaned_side_effect_attempt_becomes_unknown_before_recovery_progression() -> None:
    from datetime import UTC, datetime, timedelta

    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode
    from agentforge.infrastructure.db.models import ExternalActionRow, RunRow

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)

    side_tool_id = uuid4()
    side_version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(ToolDefinitionRow(id=side_tool_id, name="orphan_write", description="write"))
        await session.flush()
        session.add(
            ToolVersionRow(
                id=side_version_id,
                tool_id=side_tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.EXTERNAL_SIDE_EFFECT,
                implementation_ref="tests:orphan_write",
                allow_no_approval_execution=True,
                reconciliation_mode=ReconciliationMode.AUTHORITATIVE,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=DEMO_AGENT_VERSION_ID,
                tool_version_id=side_version_id,
                tool_alias="orphan_write",
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
                name="orphan_write",
                description="write",
                input_schema={"type": "object"},
                func=lambda invocation: {"must": "not be called"},
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="orphan action",
        idempotency_key="integration-d2-orphan",
        principal_scope="test-user",
    )
    claimed1 = await store.claim_next_run(worker_id="orphan-a", lease_seconds=30)
    assert claimed1 is not None
    recorder1 = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed1.execution_generation,
    )
    _, invocation = await recorder1.begin_model_invocation(
        run_id=created.id,
        invocation_id=uuid4(),
        expected_generation=claimed1.execution_generation,
    )
    invocation.complete("TOOL_PROPOSAL")
    proposal = ToolProposal.create(
        run_id=created.id,
        model_invocation_id=invocation.id,
        tool_name="orphan_write",
        arguments={"v": "same"},
    )
    prepared = ToolCoordinator(registry).prepare_side_effect(
        proposal=proposal,
        agent_version=await store.load_agent_version(DEMO_AGENT_VERSION_ID),
    )
    await recorder1.record_model_side_effect_prepared(
        invocation,
        proposal,
        prepared.call,
        prepared.snapshot,
        prepared.action,
        expected_generation=claimed1.execution_generation,
    )
    attempt = await recorder1.record_side_effect_attempt_started(
        prepared.call,
        prepared.action,
        expected_generation=claimed1.execution_generation,
    )

    async with sessions() as session, session.begin():
        row = await session.get(RunRow, created.id)
        assert row is not None
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)

    claimed2 = await store.claim_next_run(worker_id="orphan-b", lease_seconds=30)
    assert claimed2 is not None
    assert claimed2.execution_generation == 2

    async with sessions() as session:
        action = (
            await session.execute(
                select(ExternalActionRow).where(ExternalActionRow.run_id == created.id)
            )
        ).scalar_one()
        call = await session.get(ToolCallRow, action.tool_call_id)
        durable_attempt = await session.get(ToolExecutionAttemptRow, attempt.id)
        event_types = (
            (
                await session.execute(
                    select(DomainEventRow.event_type)
                    .where(DomainEventRow.run_id == created.id)
                    .order_by(DomainEventRow.sequence)
                )
            )
            .scalars()
            .all()
        )

    assert action.status is ExternalActionStatus.UNKNOWN
    assert action.current_attempt_id is None
    assert call is not None and call.status is ToolCallStatus.UNRESOLVED
    assert durable_attempt is not None
    assert durable_attempt.status is ToolExecutionAttemptStatus.UNKNOWN
    assert durable_attempt.outcome_reason == "LEASE_LOST_RESULT_NOT_DURABLE"
    assert durable_attempt.definite_not_executed is False
    assert EventType.ACTION_UNKNOWN.value in event_types

    # The new owner sees UNKNOWN before any model reasoning or replacement attempt.
    recorder2 = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed2.execution_generation,
    )
    manager2 = RunManager(
        NativeRunner(ScriptedFakeModel([FinalStep("must not reason")]), registry),
        ToolCoordinator(registry),
    )
    state_before = await store.load_run_state(created.id)
    assert (
        await manager2.execute(
            run=claimed2,
            run_state=state_before,
            agent_version=await store.load_agent_version(DEMO_AGENT_VERSION_ID),
            recorder=recorder2,
        )
        is None
    )
    state_after = await store.load_run_state(created.id)
    assert state_after.model_invocations_used == state_before.model_invocations_used
    assert state_after.tool_attempts_used == state_before.tool_attempts_used
    await engine.dispose()
'''
)
