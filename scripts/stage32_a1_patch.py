from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{path}: expected exactly one anchor, found {count}: {old[:100]!r}"
        )
    file.write_text(text.replace(old, new))


def replace_count(path: str, old: str, new: str, expected: int) -> None:
    file = Path(path)
    text = file.read_text()
    count = text.count(old)
    if count != expected:
        raise SystemExit(
            f"{path}: expected {expected} anchors, found {count}: {old[:100]!r}"
        )
    file.write_text(text.replace(old, new))


# ---------- domain ----------
replace_once(
    "src/agentforge/domain/enums.py",
    '''class ModelInvocationStatus(StrEnum):
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
''',
    '''class ToolExecutionAttemptStatus(StrEnum):
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class ModelInvocationStatus(StrEnum):
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
''',
)

replace_once(
    "src/agentforge/domain/models.py",
    '''    ToolCallStatus,
)
''',
    '''    ToolCallStatus,
    ToolExecutionAttemptStatus,
)
''',
)

replace_once(
    "src/agentforge/domain/models.py",
    '''@dataclass(frozen=True, slots=True)
class DomainEvent:
''',
    '''@dataclass(slots=True)
class ToolExecutionAttempt:
    id: UUID
    run_id: UUID
    tool_call_id: UUID
    attempt_number: int
    execution_generation: int
    status: ToolExecutionAttemptStatus = ToolExecutionAttemptStatus.STARTED
    result: Any = None
    error: str | None = None
    outcome_reason: str | None = None
    definite_not_executed: bool | None = None
    started_at: datetime = field(default_factory=utcnow)
    finished_at: datetime | None = None

    def succeed(self, result: Any) -> None:
        if self.status is not ToolExecutionAttemptStatus.STARTED:
            raise ValueError("tool attempt can only succeed from STARTED")
        self.status = ToolExecutionAttemptStatus.SUCCEEDED
        self.result = result
        self.finished_at = utcnow()

    def fail(
        self,
        error: str,
        *,
        definite_not_executed: bool | None = None,
        outcome_reason: str | None = None,
    ) -> None:
        if self.status is not ToolExecutionAttemptStatus.STARTED:
            raise ValueError("tool attempt can only fail from STARTED")
        self.status = ToolExecutionAttemptStatus.FAILED
        self.error = error
        self.definite_not_executed = definite_not_executed
        self.outcome_reason = outcome_reason
        self.finished_at = utcnow()

    def mark_unknown(self, reason: str) -> None:
        if self.status is not ToolExecutionAttemptStatus.STARTED:
            raise ValueError("tool attempt can only become UNKNOWN from STARTED")
        self.status = ToolExecutionAttemptStatus.UNKNOWN
        self.outcome_reason = reason
        self.finished_at = utcnow()


@dataclass(frozen=True, slots=True)
class DomainEvent:
''',
)

# ---------- ORM ----------
replace_once(
    "src/agentforge/infrastructure/db/models.py",
    '''    CheckConstraint,
    DateTime,
''',
    '''    Boolean,
    CheckConstraint,
    DateTime,
''',
)

replace_once(
    "src/agentforge/infrastructure/db/models.py",
    '''    ToolCallStatus,
    ToolEffectType,
)
''',
    '''    ToolCallStatus,
    ToolEffectType,
    ToolExecutionAttemptStatus,
)
''',
)

replace_once(
    "src/agentforge/infrastructure/db/models.py",
    '''class DomainEventRow(Base):
''',
    '''class ToolExecutionAttemptRow(Base):
    __tablename__ = "tool_execution_attempts"
    __table_args__ = (
        UniqueConstraint(
            "tool_call_id",
            "attempt_number",
            name="uq_tool_execution_attempts_call_number",
        ),
        Index(
            "uq_tool_execution_attempts_one_started_per_call",
            "tool_call_id",
            unique=True,
            postgresql_where=text("status = 'STARTED'"),
        ),
        Index("ix_tool_execution_attempts_run_id", "run_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False
    )
    tool_call_id: Mapped[UUID] = mapped_column(
        ForeignKey("tool_calls.id", ondelete="RESTRICT"), nullable=False
    )
    external_action_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    execution_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ToolExecutionAttemptStatus] = mapped_column(
        Enum(ToolExecutionAttemptStatus, name="tool_execution_attempt_status"),
        nullable=False,
    )
    result: Mapped[object | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    error_class: Mapped[str | None] = mapped_column(String(64))
    outcome_reason: Mapped[str | None] = mapped_column(String(120))
    definite_not_executed: Mapped[bool | None] = mapped_column(Boolean)
    adapter_metadata: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DomainEventRow(Base):
''',
)

# ---------- in-memory ExecutionJournal ----------
replace_once(
    "src/agentforge/application/run_manager.py",
    "from agentforge.domain.enums import EventType, MessageRole, RunStatus, ToolCallStatus\n",
    '''from agentforge.domain.enums import (
    EventType,
    MessageRole,
    RunStatus,
    ToolCallStatus,
    ToolExecutionAttemptStatus,
)
''',
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''    ToolCall,
    ToolProposal,
)
''',
    '''    ToolCall,
    ToolExecutionAttempt,
    ToolProposal,
)
''',
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''    tool_calls: list[ToolCall] = field(default_factory=list)
    run_state: RunState | None = None
''',
    '''    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_attempts: list[ToolExecutionAttempt] = field(default_factory=list)
    run_state: RunState | None = None
''',
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''    def _assert_no_started_model_invocations(self, run_id: UUID) -> None:
''',
    '''    def _started_tool_attempt(self, tool_call_id: UUID) -> ToolExecutionAttempt:
        attempts = [
            attempt
            for attempt in self.tool_attempts
            if attempt.tool_call_id == tool_call_id
            and attempt.status is ToolExecutionAttemptStatus.STARTED
        ]
        if len(attempts) != 1:
            raise RuntimeError(
                f"expected one STARTED ToolExecutionAttempt for {tool_call_id}, "
                f"found {len(attempts)}"
            )
        return attempts[0]

    def _next_tool_attempt_number(self, tool_call_id: UUID) -> int:
        numbers = [
            attempt.attempt_number
            for attempt in self.tool_attempts
            if attempt.tool_call_id == tool_call_id
        ]
        return max(numbers, default=0) + 1

    def _assert_no_started_tool_attempts(self, run_id: UUID) -> None:
        started = [
            attempt
            for attempt in self.tool_attempts
            if attempt.run_id == run_id
            and attempt.status is ToolExecutionAttemptStatus.STARTED
        ]
        if started:
            raise RuntimeError(
                f"cannot progress run {run_id} with STARTED "
                f"ToolExecutionAttempt {started[0].id}"
            )

    def _assert_no_started_model_invocations(self, run_id: UUID) -> None:
''',
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''        self._assert_no_started_model_invocations(call.run_id)
        self.events.append(
            DomainEvent(
                call.run_id,
                len(self.events) + 1,
                EventType.TOOL_STARTED,
                {
                    "tool_call_id": str(call.id),
                    "tool_name": call.tool_name,
                    "recovered_retry": True,
                },
            )
        )
''',
    '''        self._assert_no_started_model_invocations(call.run_id)
        self._assert_no_started_tool_attempts(call.run_id)
        attempt = ToolExecutionAttempt(
            uuid4(),
            call.run_id,
            call.id,
            self._next_tool_attempt_number(call.id),
            expected_generation,
        )
        self.tool_attempts.append(attempt)
        self.events.append(
            DomainEvent(
                call.run_id,
                len(self.events) + 1,
                EventType.TOOL_STARTED,
                {
                    "tool_call_id": str(call.id),
                    "tool_name": call.tool_name,
                    "attempt_id": str(attempt.id),
                    "attempt_number": attempt.attempt_number,
                    "recovered_retry": True,
                },
            )
        )
''',
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''        self._assert_no_active_tool_calls(run_id)
        self._assert_no_started_model_invocations(run_id)
        self.run_state.turn_count += 1
''',
    '''        self._assert_no_active_tool_calls(run_id)
        self._assert_no_started_tool_attempts(run_id)
        self._assert_no_started_model_invocations(run_id)
        self.run_state.turn_count += 1
''',
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''        self.tool_calls.append(call)
        self.events.append(
            DomainEvent(
                call.run_id,
                len(self.events) + 1,
                EventType.TOOL_STARTED,
                {"tool_call_id": str(call.id), "tool_name": call.tool_name},
            )
        )
        return self.run_state
''',
    '''        self.tool_calls.append(call)
        attempt = ToolExecutionAttempt(
            uuid4(),
            call.run_id,
            call.id,
            self._next_tool_attempt_number(call.id),
            expected_generation,
        )
        self.tool_attempts.append(attempt)
        self.events.append(
            DomainEvent(
                call.run_id,
                len(self.events) + 1,
                EventType.TOOL_STARTED,
                {
                    "tool_call_id": str(call.id),
                    "tool_name": call.tool_name,
                    "attempt_id": str(attempt.id),
                    "attempt_number": attempt.attempt_number,
                },
            )
        )
        return self.run_state
''',
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''        if call.status is not ToolCallStatus.SUCCEEDED:
            raise ValueError("tool success persistence requires a SUCCEEDED ToolCall")
        self.messages.append(
''',
    '''        if call.status is not ToolCallStatus.SUCCEEDED:
            raise ValueError("tool success persistence requires a SUCCEEDED ToolCall")
        attempt = self._started_tool_attempt(call.id)
        attempt.succeed(call.result)
        self.messages.append(
''',
)

# Only the TOOL_SUCCEEDED event in the journal has this exact block after the new attempt variable.
replace_once(
    "src/agentforge/application/run_manager.py",
    '''                {"tool_call_id": str(call.id), "tool_name": call.tool_name},
            )
        )

    async def record_tool_failed_and_fail_run(
''',
    '''                {
                    "tool_call_id": str(call.id),
                    "tool_name": call.tool_name,
                    "attempt_id": str(attempt.id),
                    "attempt_number": attempt.attempt_number,
                },
            )
        )

    async def record_tool_failed_and_fail_run(
''',
)

replace_once(
    "src/agentforge/application/run_manager.py",
    '''        if call.status is not ToolCallStatus.FAILED:
            raise ValueError("tool failure persistence requires a FAILED ToolCall")
        self._assert_no_active_tool_calls(run.id)
        self._assert_no_started_model_invocations(run.id)
''',
    '''        if call.status is not ToolCallStatus.FAILED:
            raise ValueError("tool failure persistence requires a FAILED ToolCall")
        attempt = self._started_tool_attempt(call.id)
        attempt.fail(call.error or "tool failed")
        self._assert_no_active_tool_calls(run.id)
        self._assert_no_started_tool_attempts(run.id)
        self._assert_no_started_model_invocations(run.id)
''',
)

# record_run_failed only: the exact tail is unique.
replace_once(
    "src/agentforge/application/run_manager.py",
    '''        self._assert_no_active_tool_calls(run.id)
        self._assert_no_started_model_invocations(run.id)
        self._append_event(run, EventType.RUN_FAILED, {"reason": run.failure_reason})


class RunManager:
''',
    '''        self._assert_no_active_tool_calls(run.id)
        self._assert_no_started_tool_attempts(run.id)
        self._assert_no_started_model_invocations(run.id)
        self._append_event(run, EventType.RUN_FAILED, {"reason": run.failure_reason})


class RunManager:
''',
)

# ---------- PostgreSQL recorder ----------
replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''    ToolCallStatus,
)
''',
    '''    ToolCallStatus,
    ToolExecutionAttemptStatus,
)
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''    ToolCallRow,
    ToolProposalRow,
)
''',
    '''    ToolCallRow,
    ToolExecutionAttemptRow,
    ToolProposalRow,
)
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''async def _assert_no_started_model_invocations(session: AsyncSession, run_id: UUID) -> None:
''',
    '''async def _assert_no_started_tool_attempts(session: AsyncSession, run_id: UUID) -> None:
    started_id = await session.scalar(
        select(ToolExecutionAttemptRow.id)
        .where(
            ToolExecutionAttemptRow.run_id == run_id,
            ToolExecutionAttemptRow.status == ToolExecutionAttemptStatus.STARTED,
        )
        .limit(1)
    )
    if started_id is not None:
        raise RuntimeError(
            f"cannot progress run {run_id} with STARTED ToolExecutionAttempt {started_id}"
        )


async def _lock_started_tool_attempt(
    session: AsyncSession, tool_call_id: UUID
) -> ToolExecutionAttemptRow:
    row = (
        await session.execute(
            select(ToolExecutionAttemptRow)
            .where(
                ToolExecutionAttemptRow.tool_call_id == tool_call_id,
                ToolExecutionAttemptRow.status == ToolExecutionAttemptStatus.STARTED,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise RuntimeError(f"tool call {tool_call_id} has no STARTED ToolExecutionAttempt")
    return row


async def _next_tool_attempt_number(session: AsyncSession, tool_call_id: UUID) -> int:
    current = await session.scalar(
        select(func.max(ToolExecutionAttemptRow.attempt_number)).where(
            ToolExecutionAttemptRow.tool_call_id == tool_call_id
        )
    )
    return int(current or 0) + 1


async def _assert_no_started_model_invocations(session: AsyncSession, run_id: UUID) -> None:
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''            await _assert_no_started_model_invocations(session, call.run_id)
            result = await session.execute(
''',
    '''            await _assert_no_started_model_invocations(session, call.run_id)
            await _assert_no_started_tool_attempts(session, call.run_id)
            result = await session.execute(
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''            if cast(CursorResult[Any], result).rowcount != 1:
                raise RuntimeError("recovered READ ToolCall is no longer READY")
            seq = next(iter(await _allocate_event_sequences(session, call.run_id, 1)))
            session.add(
                DomainEventRow(
                    id=uuid4(),
                    run_id=call.run_id,
                    sequence=seq,
                    event_type=EventType.TOOL_STARTED.value,
                    payload={
                        "tool_call_id": str(call.id),
                        "tool_name": call.tool_name,
                        "recovered_retry": True,
                    },
                )
            )
''',
    '''            if cast(CursorResult[Any], result).rowcount != 1:
                raise RuntimeError("recovered READ ToolCall is no longer READY")
            attempt_number = await _next_tool_attempt_number(session, call.id)
            attempt = ToolExecutionAttemptRow(
                id=uuid4(),
                run_id=call.run_id,
                tool_call_id=call.id,
                external_action_id=None,
                attempt_number=attempt_number,
                execution_generation=expected_generation,
                status=ToolExecutionAttemptStatus.STARTED,
            )
            session.add(attempt)
            seq = next(iter(await _allocate_event_sequences(session, call.run_id, 1)))
            session.add(
                DomainEventRow(
                    id=uuid4(),
                    run_id=call.run_id,
                    sequence=seq,
                    event_type=EventType.TOOL_STARTED.value,
                    payload={
                        "tool_call_id": str(call.id),
                        "tool_name": call.tool_name,
                        "attempt_id": str(attempt.id),
                        "attempt_number": attempt_number,
                        "recovered_retry": True,
                    },
                )
            )
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''            await _assert_no_active_tool_calls(session, run_id)
            await _assert_no_started_model_invocations(session, run_id)
            state = await _lock_run_state(session, run_id)
''',
    '''            await _assert_no_active_tool_calls(session, run_id)
            await _assert_no_started_tool_attempts(session, run_id)
            await _assert_no_started_model_invocations(session, run_id)
            state = await _lock_run_state(session, run_id)
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''            session.add(
                ToolCallRow(
                    id=call.id,
                    run_id=call.run_id,
                    proposal_id=call.proposal_id,
                    tool_version_id=call.tool_version_id,
                    tool_name=call.tool_name,
                    arguments=call.arguments,
                    status=call.status,
                )
            )
            seqs = list(await _allocate_event_sequences(session, invocation.run_id, 3))
''',
    '''            session.add(
                ToolCallRow(
                    id=call.id,
                    run_id=call.run_id,
                    proposal_id=call.proposal_id,
                    tool_version_id=call.tool_version_id,
                    tool_name=call.tool_name,
                    arguments=call.arguments,
                    status=call.status,
                )
            )
            await session.flush()
            attempt = ToolExecutionAttemptRow(
                id=uuid4(),
                run_id=call.run_id,
                tool_call_id=call.id,
                external_action_id=None,
                attempt_number=1,
                execution_generation=expected_generation,
                status=ToolExecutionAttemptStatus.STARTED,
            )
            session.add(attempt)
            seqs = list(await _allocate_event_sequences(session, invocation.run_id, 3))
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''                        payload={"tool_call_id": str(call.id), "tool_name": call.tool_name},
                    ),
                ]
            )
''',
    '''                        payload={
                            "tool_call_id": str(call.id),
                            "tool_name": call.tool_name,
                            "attempt_id": str(attempt.id),
                            "attempt_number": attempt.attempt_number,
                        },
                    ),
                ]
            )
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''            if cast(CursorResult[Any], result).rowcount != 1:
                raise RuntimeError("tool call no longer EXECUTING")
            message_seq = await _allocate_message_sequence(session, call.run_id)
''',
    '''            if cast(CursorResult[Any], result).rowcount != 1:
                raise RuntimeError("tool call no longer EXECUTING")
            attempt = await _lock_started_tool_attempt(session, call.id)
            attempt.status = ToolExecutionAttemptStatus.SUCCEEDED
            attempt.result = call.result
            attempt.finished_at = func.clock_timestamp()
            message_seq = await _allocate_message_sequence(session, call.run_id)
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''                    payload={"tool_call_id": str(call.id), "tool_name": call.tool_name},
                )
            )

    async def record_tool_failed_and_fail_run(
''',
    '''                    payload={
                        "tool_call_id": str(call.id),
                        "tool_name": call.tool_name,
                        "attempt_id": str(attempt.id),
                        "attempt_number": attempt.attempt_number,
                    },
                )
            )

    async def record_tool_failed_and_fail_run(
''',
)

replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''            if cast(CursorResult[Any], result).rowcount != 1:
                raise RuntimeError("tool call no longer EXECUTING")
            await _assert_no_active_tool_calls(session, run.id)
            await _assert_no_started_model_invocations(session, run.id)
            row.status = RunStatus.FAILED
''',
    '''            if cast(CursorResult[Any], result).rowcount != 1:
                raise RuntimeError("tool call no longer EXECUTING")
            attempt = await _lock_started_tool_attempt(session, call.id)
            attempt.status = ToolExecutionAttemptStatus.FAILED
            attempt.error = call.error
            attempt.finished_at = func.clock_timestamp()
            await _assert_no_active_tool_calls(session, run.id)
            await session.flush()
            await _assert_no_started_tool_attempts(session, run.id)
            await _assert_no_started_model_invocations(session, run.id)
            row.status = RunStatus.FAILED
''',
)

# Only record_run_failed tail; other terminal methods close their in-flight object first.
replace_once(
    "src/agentforge/infrastructure/db/execution_recorder.py",
    '''            await _assert_no_active_tool_calls(session, run.id)
            await _assert_no_started_model_invocations(session, run.id)
            row.status = RunStatus.FAILED
            row.failure_reason = run.failure_reason
            row.completed_at = func.clock_timestamp()
            row.owner_worker_id = None
            row.lease_expires_at = None
            seq = next(iter(await _allocate_event_sequences(session, run.id, 1)))
''',
    '''            await _assert_no_active_tool_calls(session, run.id)
            await _assert_no_started_tool_attempts(session, run.id)
            await _assert_no_started_model_invocations(session, run.id)
            row.status = RunStatus.FAILED
            row.failure_reason = run.failure_reason
            row.completed_at = func.clock_timestamp()
            row.owner_worker_id = None
            row.lease_expires_at = None
            seq = next(iter(await _allocate_event_sequences(session, run.id, 1)))
''',
)

# ---------- RuntimeStore takeover ----------
replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''    ToolEffectType,
)
''',
    '''    ToolEffectType,
    ToolExecutionAttemptStatus,
)
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''    ToolCallRow,
    ToolVersionRow,
)
''',
    '''    ToolCallRow,
    ToolExecutionAttemptRow,
    ToolVersionRow,
)
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''        call.status = ToolCallStatus.READY
        call.error = "previous executor lease expired; deterministic READ retry required"
        recovered.append(call.id)
''',
    '''        attempt = (
            await session.execute(
                select(ToolExecutionAttemptRow)
                .where(
                    ToolExecutionAttemptRow.tool_call_id == call.id,
                    ToolExecutionAttemptRow.status == ToolExecutionAttemptStatus.STARTED,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if attempt is not None:
            attempt.status = ToolExecutionAttemptStatus.UNKNOWN
            attempt.outcome_reason = "LEASE_LOST_RESULT_NOT_DURABLE"
            attempt.finished_at = func.clock_timestamp()
        call.status = ToolCallStatus.READY
        call.error = "previous executor lease expired; deterministic READ retry required"
        recovered.append(call.id)
''',
)

# ---------- migration ----------
Path("migrations/versions/0006_tool_attempts.py").write_text(
    '''"""add durable tool execution attempts

Revision ID: 0006_tool_attempts
Revises: 0005_run_terminal_shape
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_tool_attempts"
down_revision: str | None = "0005_run_terminal_shape"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    status = postgresql.ENUM(
        "STARTED",
        "SUCCEEDED",
        "FAILED",
        "UNKNOWN",
        name="tool_execution_attempt_status",
    )
    status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "tool_execution_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "tool_call_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tool_calls.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("external_action_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("execution_generation", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "STARTED",
                "SUCCEEDED",
                "FAILED",
                "UNKNOWN",
                name="tool_execution_attempt_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("error_class", sa.String(length=64), nullable=True),
        sa.Column("outcome_reason", sa.String(length=120), nullable=True),
        sa.Column("definite_not_executed", sa.Boolean(), nullable=True),
        sa.Column("adapter_metadata", postgresql.JSONB(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "tool_call_id",
            "attempt_number",
            name="uq_tool_execution_attempts_call_number",
        ),
    )
    op.create_index(
        "uq_tool_execution_attempts_one_started_per_call",
        "tool_execution_attempts",
        ["tool_call_id"],
        unique=True,
        postgresql_where=sa.text("status = 'STARTED'"),
    )
    op.create_index(
        "ix_tool_execution_attempts_run_id",
        "tool_execution_attempts",
        ["run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tool_execution_attempts_run_id",
        table_name="tool_execution_attempts",
    )
    op.drop_index(
        "uq_tool_execution_attempts_one_started_per_call",
        table_name="tool_execution_attempts",
    )
    op.drop_table("tool_execution_attempts")
    postgresql.ENUM(name="tool_execution_attempt_status").drop(
        op.get_bind(), checkfirst=True
    )
'''
)

# ---------- tests ----------
replace_once(
    "tests/unit/test_migration_contract.py",
    '''    assert "CK_RUNS_NONTERMINAL_HAS_NO_COMPLETED_AT" in ddl
''',
    '''    assert "CK_RUNS_NONTERMINAL_HAS_NO_COMPLETED_AT" in ddl
    assert "0006_TOOL_ATTEMPTS" in ddl
    assert "CREATE TABLE TOOL_EXECUTION_ATTEMPTS" in ddl
    assert "UQ_TOOL_EXECUTION_ATTEMPTS_ONE_STARTED_PER_CALL" in ddl
''',
)

replace_once(
    "tests/unit/test_postgres_contracts.py",
    '''        "tool_calls",
        "domain_events",
''',
    '''        "tool_calls",
        "tool_execution_attempts",
        "domain_events",
''',
)

replace_once(
    "tests/unit/test_postgres_contracts.py",
    '''def test_run_schema_enforces_terminal_row_shape() -> None:
''',
    '''def test_tool_execution_attempt_schema_enforces_physical_attempt_invariants() -> None:
    table = Base.metadata.tables["tool_execution_attempts"]
    assert {
        "run_id",
        "tool_call_id",
        "attempt_number",
        "execution_generation",
        "status",
        "finished_at",
    }.issubset(table.c.keys())
    indexes = {index.name: index for index in table.indexes}
    started = indexes["uq_tool_execution_attempts_one_started_per_call"]
    assert started.unique is True
    assert [column.name for column in started.columns] == ["tool_call_id"]
    where = str(started.dialect_options["postgresql"]["where"]).upper()
    assert "STATUS = 'STARTED'" in where
    unique_names = {
        constraint.name
        for constraint in table.constraints
        if constraint.name is not None
    }
    assert "uq_tool_execution_attempts_call_number" in unique_names


def test_run_schema_enforces_terminal_row_shape() -> None:
''',
)

replace_once(
    "tests/unit/test_run_manager.py",
    "from agentforge.domain.enums import EventType, RunStatus, ToolCallStatus\n",
    '''from agentforge.domain.enums import (
    EventType,
    RunStatus,
    ToolCallStatus,
    ToolExecutionAttemptStatus,
)
''',
)

replace_once(
    "tests/unit/test_run_manager.py",
    '''    ToolCall,
    ToolProposal,
)
''',
    '''    ToolCall,
    ToolExecutionAttempt,
    ToolProposal,
)
''',
)

replace_once(
    "tests/unit/test_run_manager.py",
    '''    assert journal.tool_calls[0].status is ToolCallStatus.SUCCEEDED
    assert [e.type for e in journal.events] == [
''',
    '''    assert journal.tool_calls[0].status is ToolCallStatus.SUCCEEDED
    assert len(journal.tool_attempts) == 1
    assert journal.tool_attempts[0].attempt_number == 1
    assert journal.tool_attempts[0].status is ToolExecutionAttemptStatus.SUCCEEDED
    assert [e.type for e in journal.events] == [
''',
)

replace_once(
    "tests/unit/test_run_manager.py",
    '''    recovered_call.ready()
    journal.proposals.append(proposal)
    journal.tool_calls.append(recovered_call)
''',
    '''    recovered_call.ready()
    journal.proposals.append(proposal)
    journal.tool_calls.append(recovered_call)
    previous_attempt = ToolExecutionAttempt(
        uuid4(),
        run.id,
        recovered_call.id,
        1,
        1,
    )
    previous_attempt.mark_unknown("LEASE_LOST_RESULT_NOT_DURABLE")
    journal.tool_attempts.append(previous_attempt)
''',
)

replace_once(
    "tests/unit/test_run_manager.py",
    '''    assert recovered_call.status is ToolCallStatus.SUCCEEDED
    assert state.tool_call_count == 1  # same logical ToolCall, not a new model-created one
''',
    '''    assert recovered_call.status is ToolCallStatus.SUCCEEDED
    recovered_attempts = [
        attempt
        for attempt in journal.tool_attempts
        if attempt.tool_call_id == recovered_call.id
    ]
    assert [attempt.attempt_number for attempt in recovered_attempts] == [1, 2]
    assert [attempt.status for attempt in recovered_attempts] == [
        ToolExecutionAttemptStatus.UNKNOWN,
        ToolExecutionAttemptStatus.SUCCEEDED,
    ]
    assert state.tool_call_count == 1  # same logical ToolCall, not a new model-created one
''',
)

# Integration import shape.
replace_once(
    "tests/integration/test_postgres_runtime.py",
    "from agentforge.domain.enums import EventType, RunStatus, ToolCallStatus, ToolEffectType\n",
    '''from agentforge.domain.enums import (
    EventType,
    RunStatus,
    ToolCallStatus,
    ToolEffectType,
    ToolExecutionAttemptStatus,
)
''',
)

replace_once(
    "tests/integration/test_postgres_runtime.py",
    '''    ToolCallRow,
    ToolDefinitionRow,
''',
    '''    ToolCallRow,
    ToolExecutionAttemptRow,
    ToolDefinitionRow,
''',
)

replace_once(
    "tests/integration/test_postgres_runtime.py",
    '''        assert call_row.error is not None
        assert "deterministic READ retry" in call_row.error
        event_types = (
''',
    '''        assert call_row.error is not None
        assert "deterministic READ retry" in call_row.error
        attempts = (
            (
                await session.execute(
                    select(ToolExecutionAttemptRow)
                    .where(ToolExecutionAttemptRow.tool_call_id == prepared.call.id)
                    .order_by(ToolExecutionAttemptRow.attempt_number)
                )
            )
            .scalars()
            .all()
        )
        assert len(attempts) == 1
        assert attempts[0].attempt_number == 1
        assert attempts[0].execution_generation == 1
        assert attempts[0].status is ToolExecutionAttemptStatus.UNKNOWN
        assert attempts[0].outcome_reason == "LEASE_LOST_RESULT_NOT_DURABLE"
        event_types = (
''',
)

replace_once(
    "tests/integration/test_postgres_runtime.py",
    '''        event_types = (
            (
                await session.execute(
                    select(DomainEventRow.event_type)
                    .where(DomainEventRow.run_id == run.id)
                    .order_by(DomainEventRow.sequence)
                )
            )
            .scalars()
            .all()
        )

    assert len(calls) == 1
    assert calls[0].id == original_call_id
''',
    '''        attempts = (
            (
                await session.execute(
                    select(ToolExecutionAttemptRow)
                    .where(ToolExecutionAttemptRow.tool_call_id == original_call_id)
                    .order_by(ToolExecutionAttemptRow.attempt_number)
                )
            )
            .scalars()
            .all()
        )
        event_types = (
            (
                await session.execute(
                    select(DomainEventRow.event_type)
                    .where(DomainEventRow.run_id == run.id)
                    .order_by(DomainEventRow.sequence)
                )
            )
            .scalars()
            .all()
        )

    assert len(calls) == 1
    assert calls[0].id == original_call_id
''',
)

replace_once(
    "tests/integration/test_postgres_runtime.py",
    '''    assert calls[0].status is ToolCallStatus.SUCCEEDED
    assert sum(1 for message in messages if message.role == "TOOL") == 1
''',
    '''    assert calls[0].status is ToolCallStatus.SUCCEEDED
    assert [attempt.attempt_number for attempt in attempts] == [1, 2]
    assert [attempt.execution_generation for attempt in attempts] == [1, 2]
    assert [attempt.status for attempt in attempts] == [
        ToolExecutionAttemptStatus.UNKNOWN,
        ToolExecutionAttemptStatus.SUCCEEDED,
    ]
    assert sum(1 for message in messages if message.role == "TOOL") == 1
''',
)

Path("tests/unit/test_stage32_attempt_contract.py").write_text(
    '''from pathlib import Path
from uuid import uuid4

from agentforge.domain.enums import ToolExecutionAttemptStatus
from agentforge.domain.models import ToolExecutionAttempt


ROOT = Path(__file__).resolve().parents[2]


def test_tool_execution_attempt_domain_lifecycle() -> None:
    attempt = ToolExecutionAttempt(
        uuid4(),
        uuid4(),
        uuid4(),
        1,
        7,
    )
    assert attempt.status is ToolExecutionAttemptStatus.STARTED
    attempt.succeed({"ok": True})
    assert attempt.status is ToolExecutionAttemptStatus.SUCCEEDED
    assert attempt.finished_at is not None


def test_stage32_a1_migration_is_forward_only_from_stage31_head() -> None:
    migration = (ROOT / "migrations" / "versions" / "0006_tool_attempts.py").read_text()
    assert 'revision: str = "0006_tool_attempts"' in migration
    assert 'down_revision: str | None = "0005_run_terminal_shape"' in migration
    assert "tool_execution_attempts" in migration
    assert "uq_tool_execution_attempts_one_started_per_call" in migration
'''
)
