from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import Select

from agentforge.application.errors import BusinessProgressionBlockedError, StaleExecutorError
from agentforge.application.ports import ExecutionRecorder, ReconciliationResult
from agentforge.domain.actions import ActionSnapshot, ExternalAction
from agentforge.domain.enums import (
    EventType,
    ExternalActionStatus,
    MessageRole,
    ModelInvocationStatus,
    QueueReason,
    ReconciliationAttemptStatus,
    ReconciliationBusinessResult,
    ReconciliationMode,
    RunStatus,
    ToolCallStatus,
    ToolEffectType,
    ToolExecutionAttemptStatus,
)
from agentforge.domain.models import (
    ModelInvocation,
    ReconciliationAttempt,
    Run,
    RunMessage,
    RunState,
    ToolBinding,
    ToolCall,
    ToolExecutionAttempt,
    ToolProposal,
)
from agentforge.infrastructure.db.mappers import (
    action_snapshot_from_row,
    external_action_from_row,
    message_from_row,
    run_state_from_row,
    tool_call_from_row,
)
from agentforge.infrastructure.db.models import (
    ActionSnapshotRow,
    AgentVersionToolRow,
    DomainEventRow,
    ExternalActionRow,
    ModelInvocationRow,
    ReconciliationAttemptRow,
    RunCounterRow,
    RunMessageRow,
    RunRow,
    RunStateRow,
    ToolCallRow,
    ToolExecutionAttemptRow,
    ToolProposalRow,
    ToolVersionRow,
)
from agentforge.infrastructure.db.runtime_store import _allocate_event_sequences
from agentforge.runtime.tool_coordinator import tool_result_message_content


def build_owned_run_stmt(*, run_id: UUID, expected_generation: int) -> Select[tuple[RunRow]]:
    return (
        select(RunRow)
        .where(
            RunRow.id == run_id,
            RunRow.status == RunStatus.RUNNING,
            RunRow.execution_generation == expected_generation,
            RunRow.lease_expires_at.is_not(None),
            RunRow.lease_expires_at > func.clock_timestamp(),
        )
        .with_for_update()
    )


async def _lock_owned_run(
    session: AsyncSession, *, run_id: UUID, expected_generation: int
) -> RunRow:
    row = (
        await session.execute(
            build_owned_run_stmt(run_id=run_id, expected_generation=expected_generation)
        )
    ).scalar_one_or_none()
    if row is None:
        raise StaleExecutorError(
            f"run {run_id} does not have a live lease for generation {expected_generation}"
        )
    return row


async def _lock_run_state(session: AsyncSession, run_id: UUID) -> RunStateRow:
    return (
        await session.execute(
            select(RunStateRow).where(RunStateRow.run_id == run_id).with_for_update()
        )
    ).scalar_one()


async def _database_now(session: AsyncSession) -> datetime:
    value = await session.scalar(select(func.clock_timestamp()))
    if value is None:
        raise RuntimeError("database clock_timestamp() returned no value")
    return cast(datetime, value)


async def _assert_deadline_not_expired(session: AsyncSession, run: RunRow) -> None:
    db_now = await _database_now(session)
    if db_now >= run.deadline_at:
        raise BusinessProgressionBlockedError(
            "DEADLINE_EXCEEDED",
            "run deadline has expired",
        )


def _assert_model_budget(run: RunRow, state: RunStateRow) -> None:
    if state.model_invocations_used >= run.max_model_invocations:
        raise BusinessProgressionBlockedError(
            "BUDGET_EXCEEDED",
            "max_model_invocations exhausted",
        )


def _assert_tool_budget(run: RunRow, state: RunStateRow) -> None:
    if state.tool_attempts_used >= run.max_tool_attempts:
        raise BusinessProgressionBlockedError(
            "BUDGET_EXCEEDED",
            "max_tool_attempts exhausted",
        )


async def _allocate_message_sequence(session: AsyncSession, run_id: UUID) -> int:
    result = await session.execute(
        update(RunCounterRow)
        .where(RunCounterRow.run_id == run_id)
        .values(message_sequence=RunCounterRow.message_sequence + 1)
        .returning(RunCounterRow.message_sequence)
    )
    return result.scalar_one()


async def _assert_no_active_tool_calls(session: AsyncSession, run_id: UUID) -> None:
    active_id = await session.scalar(
        select(ToolCallRow.id)
        .where(
            ToolCallRow.run_id == run_id,
            ToolCallRow.status.in_([ToolCallStatus.READY, ToolCallStatus.EXECUTING]),
        )
        .limit(1)
    )
    if active_id is not None:
        raise RuntimeError(f"cannot terminalize run {run_id} with active ToolCall {active_id}")


async def _assert_no_unresolved_actions(session: AsyncSession, run_id: UUID) -> None:
    unresolved_id = await session.scalar(
        select(ExternalActionRow.id)
        .where(
            ExternalActionRow.run_id == run_id,
            ExternalActionRow.status.in_(
                [
                    ExternalActionStatus.UNKNOWN,
                    ExternalActionStatus.RECONCILING,
                    ExternalActionStatus.MANUAL_REVIEW,
                ]
            ),
        )
        .limit(1)
    )
    if unresolved_id is not None:
        raise RuntimeError(
            f"cannot start model reasoning with unresolved ExternalAction {unresolved_id}"
        )


async def _assert_no_started_tool_attempts(session: AsyncSession, run_id: UUID) -> None:
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


async def _lock_stage32_side_effect_tool_version(
    session: AsyncSession,
    *,
    run: RunRow,
    proposal: ToolProposal,
    call: ToolCall,
) -> ToolVersionRow:
    if call.tool_version_id is None:
        raise PermissionError("side-effect ToolCall must bind a ToolVersion")
    row = (
        await session.execute(
            select(ToolVersionRow)
            .join(
                AgentVersionToolRow,
                AgentVersionToolRow.tool_version_id == ToolVersionRow.id,
            )
            .where(
                AgentVersionToolRow.agent_version_id == run.agent_version_id,
                AgentVersionToolRow.tool_alias == proposal.tool_name,
                ToolVersionRow.id == call.tool_version_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise PermissionError("side-effect ToolVersion is no longer bound to the Run AgentVersion")
    if row.effect_type not in {
        ToolEffectType.WRITE,
        ToolEffectType.EXTERNAL_SIDE_EFFECT,
    }:
        raise PermissionError("ToolVersion is not an executable Stage-3.2 side effect")
    if row.approval_required or not row.allow_no_approval_execution:
        raise PermissionError("ToolVersion is not eligible for no-approval Stage-3.2 execution")
    if row.credential_ref is not None and not row.credential_ref.strip():
        raise PermissionError("ToolVersion credential_ref configuration is invalid")
    return row


async def _assert_no_started_model_invocations(session: AsyncSession, run_id: UUID) -> None:
    started_id = await session.scalar(
        select(ModelInvocationRow.id)
        .where(
            ModelInvocationRow.run_id == run_id,
            ModelInvocationRow.status == ModelInvocationStatus.STARTED.value,
        )
        .limit(1)
    )
    if started_id is not None:
        raise RuntimeError(
            f"cannot terminalize run {run_id} with STARTED ModelInvocation {started_id}"
        )


class PostgresExecutionRecorder(ExecutionRecorder):
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        run_id: UUID,
        generation: int,
    ) -> None:
        self._sessions = session_factory
        self._run_id = run_id
        self._generation = generation

    def _assert_generation(self, expected_generation: int) -> None:
        if expected_generation != self._generation:
            raise StaleExecutorError(
                f"recorder generation {self._generation} does not match {expected_generation}"
            )

    async def list_messages(self, run_id: UUID) -> list[RunMessage]:
        if run_id != self._run_id:
            raise ValueError("recorder is scoped to one run")
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(RunMessageRow)
                    .where(RunMessageRow.run_id == run_id)
                    .order_by(RunMessageRow.sequence)
                )
            ).scalars()
            return [message_from_row(row) for row in rows]

    async def load_recoverable_read_call(self, run_id: UUID) -> ToolCall | None:
        if run_id != self._run_id:
            raise ValueError("recorder is scoped to one run")
        async with self._sessions() as session:
            rows = (
                (
                    await session.execute(
                        select(ToolCallRow)
                        .join(
                            ToolVersionRow,
                            ToolVersionRow.id == ToolCallRow.tool_version_id,
                        )
                        .outerjoin(
                            ExternalActionRow,
                            ExternalActionRow.tool_call_id == ToolCallRow.id,
                        )
                        .where(
                            ToolCallRow.run_id == run_id,
                            ToolCallRow.status == ToolCallStatus.READY,
                            ToolVersionRow.effect_type == ToolEffectType.READ,
                            ExternalActionRow.id.is_(None),
                        )
                        .order_by(ToolCallRow.id)
                    )
                )
                .scalars()
                .all()
            )
        if len(rows) > 1:
            raise RuntimeError("Wave-1 recovery found multiple READY ToolCalls")
        return tool_call_from_row(rows[0]) if rows else None

    async def load_ready_external_action(
        self,
        run_id: UUID,
    ) -> tuple[ToolCall, ActionSnapshot, ExternalAction] | None:
        if run_id != self._run_id:
            raise ValueError("recorder is scoped to one run")
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(ExternalActionRow, ToolCallRow, ActionSnapshotRow)
                    .join(ToolCallRow, ToolCallRow.id == ExternalActionRow.tool_call_id)
                    .join(
                        ActionSnapshotRow,
                        ActionSnapshotRow.id == ExternalActionRow.action_snapshot_id,
                    )
                    .where(
                        ExternalActionRow.run_id == run_id,
                        ExternalActionRow.status == ExternalActionStatus.READY,
                        ExternalActionRow.current_attempt_id.is_(None),
                        ToolCallRow.status == ToolCallStatus.READY,
                    )
                )
            ).all()
        if len(rows) > 1:
            raise RuntimeError("found multiple READY ExternalActions for one Run")
        if not rows:
            return None
        action_row, call_row, snapshot_row = rows[0]
        return (
            tool_call_from_row(call_row),
            action_snapshot_from_row(snapshot_row),
            external_action_from_row(action_row),
        )

    async def load_unknown_external_action(
        self,
        run_id: UUID,
    ) -> tuple[ToolCall, ActionSnapshot, ExternalAction] | None:
        if run_id != self._run_id:
            raise ValueError("recorder is scoped to one run")
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(ExternalActionRow, ToolCallRow, ActionSnapshotRow)
                    .join(ToolCallRow, ToolCallRow.id == ExternalActionRow.tool_call_id)
                    .join(
                        ActionSnapshotRow,
                        ActionSnapshotRow.id == ExternalActionRow.action_snapshot_id,
                    )
                    .where(
                        ExternalActionRow.run_id == run_id,
                        ExternalActionRow.status == ExternalActionStatus.UNKNOWN,
                        ExternalActionRow.current_attempt_id.is_(None),
                        ToolCallRow.status == ToolCallStatus.UNRESOLVED,
                    )
                )
            ).all()
        if len(rows) > 1:
            raise RuntimeError("found multiple UNKNOWN ExternalActions for one Run")
        if not rows:
            return None
        action_row, call_row, snapshot_row = rows[0]
        return (
            tool_call_from_row(call_row),
            action_snapshot_from_row(snapshot_row),
            external_action_from_row(action_row),
        )

    async def load_reconciliation_external_action(
        self,
        run_id: UUID,
    ) -> tuple[ToolCall, ActionSnapshot, ExternalAction] | None:
        if run_id != self._run_id:
            raise ValueError("recorder is scoped to one run")
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(ExternalActionRow, ToolCallRow, ActionSnapshotRow)
                    .join(ToolCallRow, ToolCallRow.id == ExternalActionRow.tool_call_id)
                    .join(
                        ActionSnapshotRow,
                        ActionSnapshotRow.id == ExternalActionRow.action_snapshot_id,
                    )
                    .where(
                        ExternalActionRow.run_id == run_id,
                        ExternalActionRow.status.in_(
                            [ExternalActionStatus.UNKNOWN, ExternalActionStatus.RECONCILING]
                        ),
                        ExternalActionRow.current_attempt_id.is_(None),
                        ToolCallRow.status == ToolCallStatus.UNRESOLVED,
                    )
                )
            ).all()
        if len(rows) > 1:
            raise RuntimeError("found multiple reconciliation ExternalActions for one Run")
        if not rows:
            return None
        action_row, call_row, snapshot_row = rows[0]
        return (
            tool_call_from_row(call_row),
            action_snapshot_from_row(snapshot_row),
            external_action_from_row(action_row),
        )

    async def record_action_manual_review(
        self,
        call: ToolCall,
        action: ExternalAction,
        run: Run,
        reason: str,
        *,
        expected_generation: int,
    ) -> None:
        self._assert_generation(expected_generation)
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
            if action_row.status not in {
                ExternalActionStatus.UNKNOWN,
                ExternalActionStatus.RECONCILING,
            }:
                raise RuntimeError("manual review action is no longer unresolved")
            if call_row.status is not ToolCallStatus.UNRESOLVED:
                raise RuntimeError("manual review ToolCall is no longer UNRESOLVED")
            started_reconcile = await session.scalar(
                select(ReconciliationAttemptRow.id)
                .where(
                    ReconciliationAttemptRow.external_action_id == action.id,
                    ReconciliationAttemptRow.status == ReconciliationAttemptStatus.STARTED,
                )
                .limit(1)
            )
            if started_reconcile is not None:
                raise RuntimeError("cannot enter manual review with STARTED reconciliation")
            action_row.status = ExternalActionStatus.MANUAL_REVIEW
            action_row.updated_at = func.clock_timestamp()
            run_row.status = RunStatus.WAITING_ACTION_RESOLUTION
            run_row.queue_reason = None
            run_row.available_at = None
            run_row.owner_worker_id = None
            run_row.lease_expires_at = None
            seq = next(iter(await _allocate_event_sequences(session, run.id, 1)))
            session.add(
                DomainEventRow(
                    id=uuid4(),
                    run_id=run.id,
                    sequence=seq,
                    event_type=EventType.ACTION_MANUAL_REVIEW.value,
                    payload={
                        "external_action_id": str(action.id),
                        "operation_id": str(action.operation_id),
                        "reason": reason,
                    },
                )
            )
            await session.flush()
        action.manual_review()
        run.wait_for_action_resolution()

    async def record_reconciliation_started(
        self,
        call: ToolCall,
        action: ExternalAction,
        run: Run,
        *,
        max_attempts: int,
        expected_generation: int,
    ) -> ReconciliationAttempt | None:
        self._assert_generation(expected_generation)
        if max_attempts <= 0:
            raise ValueError("reconciliation max_attempts must be positive")
        attempt_id = uuid4()
        attempt_number = 0
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
            if action_row.status not in {
                ExternalActionStatus.UNKNOWN,
                ExternalActionStatus.RECONCILING,
            }:
                raise RuntimeError("ExternalAction is not eligible for reconciliation")
            if action_row.current_attempt_id is not None:
                raise RuntimeError("reconciliation cannot overlap side-effect authorization")
            if call_row.status is not ToolCallStatus.UNRESOLVED:
                raise RuntimeError("reconciliation ToolCall is not UNRESOLVED")
            await _assert_no_started_model_invocations(session, run.id)
            await _assert_no_started_tool_attempts(session, run.id)
            started = await session.scalar(
                select(ReconciliationAttemptRow.id)
                .where(
                    ReconciliationAttemptRow.external_action_id == action.id,
                    ReconciliationAttemptRow.status == ReconciliationAttemptStatus.STARTED,
                )
                .limit(1)
            )
            if started is not None:
                raise RuntimeError("reconciliation attempt already STARTED")
            count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(ReconciliationAttemptRow)
                    .where(ReconciliationAttemptRow.external_action_id == action.id)
                )
                or 0
            )
            if count >= max_attempts:
                action_row.status = ExternalActionStatus.MANUAL_REVIEW
                action_row.updated_at = func.clock_timestamp()
                run_row.status = RunStatus.WAITING_ACTION_RESOLUTION
                run_row.queue_reason = None
                run_row.available_at = None
                run_row.owner_worker_id = None
                run_row.lease_expires_at = None
                seq = next(iter(await _allocate_event_sequences(session, run.id, 1)))
                session.add(
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seq,
                        event_type=EventType.ACTION_MANUAL_REVIEW.value,
                        payload={
                            "external_action_id": str(action.id),
                            "operation_id": str(action.operation_id),
                            "reason": "RECONCILIATION_BUDGET_EXHAUSTED",
                        },
                    )
                )
                await session.flush()
                action.manual_review()
                run.wait_for_action_resolution()
                return None

            attempt_number = count + 1
            session.add(
                ReconciliationAttemptRow(
                    id=attempt_id,
                    run_id=run.id,
                    external_action_id=action.id,
                    attempt_number=attempt_number,
                    execution_generation=expected_generation,
                    status=ReconciliationAttemptStatus.STARTED,
                )
            )
            action_row.status = ExternalActionStatus.RECONCILING
            action_row.updated_at = func.clock_timestamp()
            seq = next(iter(await _allocate_event_sequences(session, run.id, 1)))
            session.add(
                DomainEventRow(
                    id=uuid4(),
                    run_id=run.id,
                    sequence=seq,
                    event_type=EventType.RECONCILIATION_STARTED.value,
                    payload={
                        "external_action_id": str(action.id),
                        "attempt_id": str(attempt_id),
                        "attempt_number": attempt_number,
                    },
                )
            )
            await session.flush()

        action.start_reconciliation()
        return ReconciliationAttempt(
            attempt_id,
            run.id,
            action.id,
            attempt_number,
            expected_generation,
        )

    async def record_reconciliation_failed(
        self,
        action: ExternalAction,
        attempt: ReconciliationAttempt,
        run: Run,
        *,
        error: str,
        max_attempts: int,
        initial_backoff_seconds: int,
        max_backoff_seconds: int,
        expected_generation: int,
    ) -> bool:
        self._assert_generation(expected_generation)
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
            attempt_row = (
                await session.execute(
                    select(ReconciliationAttemptRow)
                    .where(
                        ReconciliationAttemptRow.id == attempt.id,
                        ReconciliationAttemptRow.external_action_id == action.id,
                    )
                    .with_for_update()
                )
            ).scalar_one()
            if (
                action_row.status is not ExternalActionStatus.RECONCILING
                or attempt_row.status is not ReconciliationAttemptStatus.STARTED
            ):
                raise RuntimeError("reconciliation request failure lost current authority")
            db_now = await _database_now(session)
            attempt_row.status = ReconciliationAttemptStatus.FAILED
            attempt_row.error = error
            attempt_row.outcome_reason = "RECONCILIATION_REQUEST_FAILED"
            attempt_row.finished_at = db_now

            seq_count = 2 if attempt.attempt_number < max_attempts else 2
            seqs = list(await _allocate_event_sequences(session, run.id, seq_count))
            session.add(
                DomainEventRow(
                    id=uuid4(),
                    run_id=run.id,
                    sequence=seqs[0],
                    event_type=EventType.RECONCILIATION_FAILED.value,
                    payload={
                        "external_action_id": str(action.id),
                        "attempt_id": str(attempt.id),
                        "attempt_number": attempt.attempt_number,
                        "error": error,
                    },
                )
            )
            if attempt.attempt_number < max_attempts:
                delay_seconds = min(
                    initial_backoff_seconds * (2 ** (attempt.attempt_number - 1)),
                    max_backoff_seconds,
                )
                run_row.status = RunStatus.QUEUED
                run_row.queue_reason = QueueReason.RETRY
                run_row.available_at = db_now + timedelta(seconds=delay_seconds)
                run_row.owner_worker_id = None
                run_row.lease_expires_at = None
                session.add(
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[1],
                        event_type=EventType.RECONCILIATION_RETRY_SCHEDULED.value,
                        payload={
                            "external_action_id": str(action.id),
                            "attempt_number": attempt.attempt_number,
                            "delay_seconds": delay_seconds,
                        },
                    )
                )
                await session.flush()
                attempt.fail(error, outcome_reason="RECONCILIATION_REQUEST_FAILED")
                run.status = RunStatus.QUEUED
                run.queue_reason = QueueReason.RETRY
                run.available_at = db_now + timedelta(seconds=delay_seconds)
                run.owner_worker_id = None
                run.lease_expires_at = None
                return True

            action_row.status = ExternalActionStatus.MANUAL_REVIEW
            action_row.updated_at = db_now
            run_row.status = RunStatus.WAITING_ACTION_RESOLUTION
            run_row.queue_reason = None
            run_row.available_at = None
            run_row.owner_worker_id = None
            run_row.lease_expires_at = None
            session.add(
                DomainEventRow(
                    id=uuid4(),
                    run_id=run.id,
                    sequence=seqs[1],
                    event_type=EventType.ACTION_MANUAL_REVIEW.value,
                    payload={
                        "external_action_id": str(action.id),
                        "operation_id": str(action.operation_id),
                        "reason": "RECONCILIATION_BUDGET_EXHAUSTED",
                    },
                )
            )
            await session.flush()
        attempt.fail(error, outcome_reason="RECONCILIATION_REQUEST_FAILED")
        action.manual_review()
        run.wait_for_action_resolution()
        return False

    async def record_reconciliation_result(
        self,
        call: ToolCall,
        action: ExternalAction,
        attempt: ReconciliationAttempt,
        run: Run,
        result: ReconciliationResult,
        *,
        binding: ToolBinding,
        expected_generation: int,
    ) -> RunMessage | None:
        self._assert_generation(expected_generation)
        returned_message: RunMessage | None = None
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
            attempt_row = (
                await session.execute(
                    select(ReconciliationAttemptRow)
                    .where(
                        ReconciliationAttemptRow.id == attempt.id,
                        ReconciliationAttemptRow.external_action_id == action.id,
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
            if (
                action_row.status is not ExternalActionStatus.RECONCILING
                or attempt_row.status is not ReconciliationAttemptStatus.STARTED
                or call_row.status is not ToolCallStatus.UNRESOLVED
            ):
                raise RuntimeError("reconciliation result lost current authority")

            db_now = await _database_now(session)
            attempt_row.status = ReconciliationAttemptStatus.SUCCEEDED
            attempt_row.business_result = result.outcome
            attempt_row.evidence = result.evidence
            attempt_row.finished_at = db_now
            seqs = list(await _allocate_event_sequences(session, run.id, 3))
            session.add(
                DomainEventRow(
                    id=uuid4(),
                    run_id=run.id,
                    sequence=seqs[0],
                    event_type=EventType.RECONCILIATION_SUCCEEDED.value,
                    payload={
                        "external_action_id": str(action.id),
                        "attempt_id": str(attempt.id),
                        "attempt_number": attempt.attempt_number,
                        "business_result": result.outcome.value,
                    },
                )
            )

            if result.outcome is ReconciliationBusinessResult.SUCCEEDED:
                action_row.status = ExternalActionStatus.SUCCEEDED
                action_row.updated_at = db_now
                call_row.status = ToolCallStatus.SUCCEEDED
                call_row.error = None
                call_row.result = {
                    "reconciliation": "SUCCEEDED",
                    "evidence": result.evidence,
                }
                message_seq = await _allocate_message_sequence(session, run.id)
                session.add(
                    RunMessageRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=message_seq,
                        role=MessageRole.TOOL.value,
                        content=tool_result_message_content(call_row.result),
                        source_id=call.id,
                    )
                )
                session.add(
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[1],
                        event_type=EventType.ACTION_SUCCEEDED.value,
                        payload={
                            "external_action_id": str(action.id),
                            "operation_id": str(action.operation_id),
                            "source": "RECONCILIATION",
                        },
                    )
                )
                session.add(
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[2],
                        event_type=EventType.TOOL_SUCCEEDED.value,
                        payload={
                            "tool_call_id": str(call.id),
                            "tool_name": call.tool_name,
                            "source": "RECONCILIATION",
                        },
                    )
                )
                returned_message = RunMessage(
                    run.id,
                    message_seq,
                    MessageRole.TOOL,
                    tool_result_message_content(call_row.result),
                    call.id,
                )

            elif result.outcome is ReconciliationBusinessResult.FAILED:
                action_row.status = ExternalActionStatus.FAILED
                action_row.updated_at = db_now
                call_row.status = ToolCallStatus.FAILED
                call_row.error = "reconciliation confirmed action failure"
                run_row.status = RunStatus.FAILED
                run_row.failure_reason = "RECONCILIATION_CONFIRMED_ACTION_FAILED"
                run_row.completed_at = db_now
                run_row.owner_worker_id = None
                run_row.lease_expires_at = None
                session.add(
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[1],
                        event_type=EventType.ACTION_FAILED.value,
                        payload={
                            "external_action_id": str(action.id),
                            "operation_id": str(action.operation_id),
                            "source": "RECONCILIATION",
                        },
                    )
                )
                session.add(
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[2],
                        event_type=EventType.RUN_FAILED.value,
                        payload={"reason": "RECONCILIATION_CONFIRMED_ACTION_FAILED"},
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
                    await session.scalar(
                        select(func.max(ToolExecutionAttemptRow.attempt_number)).where(
                            ToolExecutionAttemptRow.external_action_id == action.id
                        )
                    )
                    or 0
                )
                state = await _lock_run_state(session, run.id)
                delay_seconds = binding.side_effect_retry_delay_seconds(max(physical_number, 1))
                due_at = db_now + timedelta(seconds=delay_seconds)
                retry_allowed = (
                    physical_number < binding.side_effect_retry_max_attempts
                    and state.tool_attempts_used < run_row.max_tool_attempts
                    and due_at < run_row.deadline_at
                )
                if retry_allowed:
                    action_row.status = ExternalActionStatus.READY
                    action_row.updated_at = db_now
                    call_row.status = ToolCallStatus.READY
                    call_row.error = "reconciliation proved NOT_EXECUTED"
                    run_row.status = RunStatus.QUEUED
                    run_row.queue_reason = QueueReason.RETRY
                    run_row.available_at = due_at
                    run_row.owner_worker_id = None
                    run_row.lease_expires_at = None
                    session.add(
                        DomainEventRow(
                            id=uuid4(),
                            run_id=run.id,
                            sequence=seqs[1],
                            event_type=EventType.ACTION_RETRY_READY.value,
                            payload={
                                "external_action_id": str(action.id),
                                "operation_id": str(action.operation_id),
                                "source": "RECONCILIATION_NOT_EXECUTED",
                            },
                        )
                    )
                    session.add(
                        DomainEventRow(
                            id=uuid4(),
                            run_id=run.id,
                            sequence=seqs[2],
                            event_type=EventType.TOOL_RETRY_SCHEDULED.value,
                            payload={
                                "tool_call_id": str(call.id),
                                "attempt_number": physical_number,
                                "delay_seconds": delay_seconds,
                                "source": "RECONCILIATION",
                            },
                        )
                    )
                elif physical_number >= binding.side_effect_retry_max_attempts:
                    action_row.status = ExternalActionStatus.FAILED
                    action_row.updated_at = db_now
                    call_row.status = ToolCallStatus.FAILED
                    call_row.error = "side-effect retry policy exhausted after reconciliation"
                    run_row.status = RunStatus.FAILED
                    run_row.failure_reason = "SIDE_EFFECT_RETRY_EXHAUSTED_AFTER_RECONCILIATION"
                    run_row.completed_at = db_now
                    run_row.owner_worker_id = None
                    run_row.lease_expires_at = None
                    session.add(
                        DomainEventRow(
                            id=uuid4(),
                            run_id=run.id,
                            sequence=seqs[1],
                            event_type=EventType.ACTION_FAILED.value,
                            payload={
                                "external_action_id": str(action.id),
                                "operation_id": str(action.operation_id),
                                "reason": run_row.failure_reason,
                            },
                        )
                    )
                    session.add(
                        DomainEventRow(
                            id=uuid4(),
                            run_id=run.id,
                            sequence=seqs[2],
                            event_type=EventType.RUN_FAILED.value,
                            payload={"reason": run_row.failure_reason},
                        )
                    )
                else:
                    reason = (
                        "BUDGET_EXCEEDED: max_tool_attempts exhausted"
                        if state.tool_attempts_used >= run_row.max_tool_attempts
                        else "DEADLINE_EXCEEDED: side-effect retry due time reaches run deadline"
                    )
                    action_row.status = ExternalActionStatus.ABORTED
                    action_row.updated_at = db_now
                    call_row.status = ToolCallStatus.NOT_EXECUTED
                    call_row.error = reason
                    run_row.status = RunStatus.FAILED
                    run_row.failure_reason = reason
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
                                "reason": reason,
                            },
                        )
                    )
                    session.add(
                        DomainEventRow(
                            id=uuid4(),
                            run_id=run.id,
                            sequence=seqs[2],
                            event_type=EventType.RUN_FAILED.value,
                            payload={"reason": reason},
                        )
                    )

            else:
                reason = (
                    "RECONCILIATION_UNKNOWN"
                    if result.outcome is ReconciliationBusinessResult.UNKNOWN
                    else "BEST_EFFORT_NOT_EXECUTED_UNSAFE"
                )
                action_row.status = ExternalActionStatus.MANUAL_REVIEW
                action_row.updated_at = db_now
                run_row.status = RunStatus.WAITING_ACTION_RESOLUTION
                run_row.queue_reason = None
                run_row.available_at = None
                run_row.owner_worker_id = None
                run_row.lease_expires_at = None
                session.add(
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[1],
                        event_type=EventType.ACTION_MANUAL_REVIEW.value,
                        payload={
                            "external_action_id": str(action.id),
                            "operation_id": str(action.operation_id),
                            "reason": reason,
                        },
                    )
                )
                session.add(
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[2],
                        event_type=EventType.RUN_YIELDED.value,
                        payload={"reason": "WAITING_ACTION_RESOLUTION"},
                    )
                )
            await session.flush()

        attempt.succeed(result.outcome, result.evidence)
        if result.outcome is ReconciliationBusinessResult.SUCCEEDED:
            action.reconcile_succeeded()
            call.status = ToolCallStatus.SUCCEEDED
            call.error = None
            call.result = {"reconciliation": "SUCCEEDED", "evidence": result.evidence}
        elif result.outcome is ReconciliationBusinessResult.FAILED:
            action.reconcile_failed()
            call.status = ToolCallStatus.FAILED
            call.error = "reconciliation confirmed action failure"
            run.status = RunStatus.FAILED
            run.failure_reason = "RECONCILIATION_CONFIRMED_ACTION_FAILED"
            run.completed_at = datetime.now(run.deadline_at.tzinfo)
            run.owner_worker_id = None
            run.lease_expires_at = None
        elif result.outcome is ReconciliationBusinessResult.NOT_EXECUTED and (
            binding.reconciliation_mode is ReconciliationMode.AUTHORITATIVE
            or (
                binding.reconciliation_mode is ReconciliationMode.BEST_EFFORT
                and binding.idempotency_supported
            )
        ):
            if run_row.status is RunStatus.QUEUED:
                action.reconcile_retry_ready()
                call.status = ToolCallStatus.READY
                call.error = "reconciliation proved NOT_EXECUTED"
                run.status = RunStatus.QUEUED
                run.queue_reason = QueueReason.RETRY
                run.available_at = run_row.available_at
                run.owner_worker_id = None
                run.lease_expires_at = None
            elif action_row.status is ExternalActionStatus.FAILED:
                action.reconcile_failed()
                call.status = ToolCallStatus.FAILED
                call.error = call_row.error
                run.status = RunStatus.FAILED
                run.failure_reason = run_row.failure_reason
                run.completed_at = run_row.completed_at
                run.owner_worker_id = None
                run.lease_expires_at = None
            else:
                action.reconcile_abort_not_executed()
                call.status = ToolCallStatus.NOT_EXECUTED
                call.error = call_row.error
                run.status = RunStatus.FAILED
                run.failure_reason = run_row.failure_reason
                run.completed_at = run_row.completed_at
                run.owner_worker_id = None
                run.lease_expires_at = None
        else:
            action.manual_review()
            run.wait_for_action_resolution()
        return returned_message

    async def record_side_effect_attempt_started(
        self,
        call: ToolCall,
        action: ExternalAction,
        *,
        expected_generation: int,
    ) -> ToolExecutionAttempt:
        """Action Commit: durable authorization must commit before adapter I/O."""
        self._assert_generation(expected_generation)
        if call.status is not ToolCallStatus.READY:
            raise ValueError("Action Commit requires READY ToolCall")
        if action.status is not ExternalActionStatus.READY or action.current_attempt_id is not None:
            raise ValueError("Action Commit requires READY ExternalAction")
        if action.run_id != call.run_id or action.tool_call_id != call.id:
            raise ValueError("ExternalAction does not reference ToolCall")

        attempt_id = uuid4()
        attempt_number = 0
        async with self._sessions() as session, session.begin():
            run_row = await _lock_owned_run(
                session,
                run_id=call.run_id,
                expected_generation=expected_generation,
            )
            action_row = (
                await session.execute(
                    select(ExternalActionRow)
                    .where(
                        ExternalActionRow.id == action.id,
                        ExternalActionRow.run_id == call.run_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if (
                action_row is None
                or action_row.status is not ExternalActionStatus.READY
                or action_row.current_attempt_id is not None
                or action_row.tool_call_id != call.id
                or action_row.operation_id != action.operation_id
            ):
                raise RuntimeError("ExternalAction is no longer READY for Action Commit")

            call_row = (
                await session.execute(
                    select(ToolCallRow)
                    .where(
                        ToolCallRow.id == call.id,
                        ToolCallRow.run_id == call.run_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if (
                call_row is None
                or call_row.status is not ToolCallStatus.READY
                or call_row.tool_version_id != call.tool_version_id
            ):
                raise RuntimeError("ToolCall is no longer READY for Action Commit")

            conflicting = await session.scalar(
                select(ToolCallRow.id)
                .where(
                    ToolCallRow.run_id == call.run_id,
                    ToolCallRow.id != call.id,
                    ToolCallRow.status.in_([ToolCallStatus.READY, ToolCallStatus.EXECUTING]),
                )
                .limit(1)
            )
            if conflicting is not None:
                raise RuntimeError(f"conflicting active ToolCall exists: {conflicting}")
            await _assert_no_started_model_invocations(session, call.run_id)
            await _assert_no_started_tool_attempts(session, call.run_id)
            state = await _lock_run_state(session, call.run_id)
            await _assert_deadline_not_expired(session, run_row)
            _assert_tool_budget(run_row, state)

            snapshot_row = await session.get(ActionSnapshotRow, action_row.action_snapshot_id)
            if snapshot_row is None:
                raise RuntimeError("ExternalAction snapshot is missing")
            if (
                snapshot_row.operation_id != action_row.operation_id
                or snapshot_row.tool_version_id != call_row.tool_version_id
                or dict(snapshot_row.arguments) != dict(call_row.arguments)
            ):
                raise RuntimeError("ActionSnapshot no longer matches durable action identity")

            attempt_number = await _next_tool_attempt_number(session, call.id)
            attempt_row = ToolExecutionAttemptRow(
                id=attempt_id,
                run_id=call.run_id,
                tool_call_id=call.id,
                external_action_id=action.id,
                attempt_number=attempt_number,
                execution_generation=expected_generation,
                status=ToolExecutionAttemptStatus.STARTED,
            )
            session.add(attempt_row)
            await session.flush()

            state.tool_attempts_used += 1
            state.state_version += 1
            call_row.status = ToolCallStatus.EXECUTING
            call_row.error = None
            action_row.status = ExternalActionStatus.EXECUTING
            action_row.current_attempt_id = attempt_id
            action_row.updated_at = func.clock_timestamp()

            seqs = list(await _allocate_event_sequences(session, call.run_id, 2))
            session.add_all(
                [
                    DomainEventRow(
                        id=uuid4(),
                        run_id=call.run_id,
                        sequence=seqs[0],
                        event_type=EventType.ACTION_COMMITTED.value,
                        payload={
                            "tool_call_id": str(call.id),
                            "external_action_id": str(action.id),
                            "operation_id": str(action.operation_id),
                            "attempt_id": str(attempt_id),
                            "attempt_number": attempt_number,
                        },
                    ),
                    DomainEventRow(
                        id=uuid4(),
                        run_id=call.run_id,
                        sequence=seqs[1],
                        event_type=EventType.TOOL_STARTED.value,
                        payload={
                            "tool_call_id": str(call.id),
                            "tool_name": call.tool_name,
                            "external_action_id": str(action.id),
                            "attempt_id": str(attempt_id),
                            "attempt_number": attempt_number,
                        },
                    ),
                ]
            )
            await session.flush()

        attempt = ToolExecutionAttempt(
            attempt_id,
            call.run_id,
            call.id,
            attempt_number,
            expected_generation,
            external_action_id=action.id,
        )
        call.start()
        action.start(attempt.id)
        return attempt

    async def record_ready_side_effect_blocked_and_fail_run(
        self,
        call: ToolCall,
        action: ExternalAction,
        run: Run,
        reason: str,
        *,
        expected_generation: int,
    ) -> None:
        """Stabilize a pre-commit action that can no longer execute."""
        self._assert_generation(expected_generation)
        if call.status is not ToolCallStatus.READY:
            raise ValueError("blocked action stabilization requires READY ToolCall")
        if action.status is not ExternalActionStatus.READY:
            raise ValueError("blocked action stabilization requires READY ExternalAction")
        if run.status is not RunStatus.FAILED:
            raise ValueError("blocked action stabilization requires FAILED Run")

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
            if (
                action_row.status is not ExternalActionStatus.READY
                or action_row.current_attempt_id is not None
                or call_row.status is not ToolCallStatus.READY
            ):
                raise RuntimeError("blocked action is no longer pre-commit READY")
            await _assert_no_started_tool_attempts(session, run.id)
            action_row.status = ExternalActionStatus.ABORTED
            action_row.current_attempt_id = None
            action_row.updated_at = func.clock_timestamp()
            call_row.status = ToolCallStatus.NOT_EXECUTED
            call_row.error = reason
            run_row.status = RunStatus.FAILED
            run_row.failure_reason = reason
            run_row.completed_at = func.clock_timestamp()
            run_row.owner_worker_id = None
            run_row.lease_expires_at = None
            seqs = list(await _allocate_event_sequences(session, run.id, 2))
            session.add_all(
                [
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[0],
                        event_type=EventType.ACTION_ABORTED.value,
                        payload={
                            "tool_call_id": str(call.id),
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

        call.not_executed(reason)
        action.abort()

    async def record_side_effect_succeeded(
        self,
        call: ToolCall,
        action: ExternalAction,
        attempt: ToolExecutionAttempt,
        message: RunMessage,
        *,
        expected_generation: int,
    ) -> None:
        """Commit a current side-effect attempt's successful business result."""
        self._assert_generation(expected_generation)
        if call.status is not ToolCallStatus.SUCCEEDED:
            raise ValueError("side-effect success requires SUCCEEDED ToolCall")
        if action.status is not ExternalActionStatus.EXECUTING:
            raise ValueError("side-effect success requires EXECUTING ExternalAction")
        if action.current_attempt_id != attempt.id:
            raise ValueError("side-effect success attempt is not current")

        async with self._sessions() as session, session.begin():
            await _lock_owned_run(
                session,
                run_id=call.run_id,
                expected_generation=expected_generation,
            )
            action_row = (
                await session.execute(
                    select(ExternalActionRow)
                    .where(
                        ExternalActionRow.id == action.id,
                        ExternalActionRow.run_id == call.run_id,
                    )
                    .with_for_update()
                )
            ).scalar_one()
            call_row = (
                await session.execute(
                    select(ToolCallRow)
                    .where(
                        ToolCallRow.id == call.id,
                        ToolCallRow.run_id == call.run_id,
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
                raise RuntimeError("side-effect result lost current-attempt authorization")

            attempt_row.status = ToolExecutionAttemptStatus.SUCCEEDED
            attempt_row.result = call.result
            attempt_row.finished_at = func.clock_timestamp()
            call_row.status = ToolCallStatus.SUCCEEDED
            call_row.result = call.result
            action_row.status = ExternalActionStatus.SUCCEEDED
            action_row.current_attempt_id = None
            action_row.updated_at = func.clock_timestamp()

            message_seq = await _allocate_message_sequence(session, call.run_id)
            session.add(
                RunMessageRow(
                    id=uuid4(),
                    run_id=call.run_id,
                    sequence=message_seq,
                    role=message.role.value,
                    content=message.content,
                    source_id=message.source_id,
                )
            )
            seqs = list(await _allocate_event_sequences(session, call.run_id, 2))
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

    async def record_side_effect_unknown(
        self,
        call: ToolCall,
        action: ExternalAction,
        attempt: ToolExecutionAttempt,
        *,
        error: str,
        error_class: str,
        outcome_reason: str,
        expected_generation: int,
    ) -> None:
        """Persist possible execution as UNKNOWN; never convert uncertainty to retry."""
        self._assert_generation(expected_generation)
        if call.status is not ToolCallStatus.EXECUTING:
            raise ValueError("UNKNOWN persistence requires EXECUTING ToolCall")
        if action.status is not ExternalActionStatus.EXECUTING:
            raise ValueError("UNKNOWN persistence requires EXECUTING ExternalAction")
        if action.current_attempt_id != attempt.id:
            raise ValueError("UNKNOWN persistence attempt is not current")

        async with self._sessions() as session, session.begin():
            await _lock_owned_run(
                session,
                run_id=call.run_id,
                expected_generation=expected_generation,
            )
            action_row = (
                await session.execute(
                    select(ExternalActionRow)
                    .where(
                        ExternalActionRow.id == action.id,
                        ExternalActionRow.run_id == call.run_id,
                    )
                    .with_for_update()
                )
            ).scalar_one()
            call_row = (
                await session.execute(
                    select(ToolCallRow)
                    .where(
                        ToolCallRow.id == call.id,
                        ToolCallRow.run_id == call.run_id,
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
                raise RuntimeError("side-effect UNKNOWN result lost current-attempt authorization")

            attempt_row.status = ToolExecutionAttemptStatus.UNKNOWN
            attempt_row.error = error
            attempt_row.error_class = error_class
            attempt_row.definite_not_executed = False
            attempt_row.outcome_reason = outcome_reason
            attempt_row.finished_at = func.clock_timestamp()
            call_row.status = ToolCallStatus.UNRESOLVED
            call_row.error = error
            action_row.status = ExternalActionStatus.UNKNOWN
            action_row.current_attempt_id = None
            action_row.updated_at = func.clock_timestamp()

            seq = next(iter(await _allocate_event_sequences(session, call.run_id, 1)))
            session.add(
                DomainEventRow(
                    id=uuid4(),
                    run_id=call.run_id,
                    sequence=seq,
                    event_type=EventType.ACTION_UNKNOWN.value,
                    payload={
                        "tool_call_id": str(call.id),
                        "external_action_id": str(action.id),
                        "operation_id": str(action.operation_id),
                        "attempt_id": str(attempt.id),
                        "attempt_number": attempt.attempt_number,
                        "error_class": error_class,
                        "outcome_reason": outcome_reason,
                    },
                )
            )
            await session.flush()

        attempt.mark_unknown(
            outcome_reason,
            error=error,
            error_class=error_class,
        )
        call.unresolve(error)
        action.mark_unknown()

    async def record_side_effect_definite_failure_and_fail_run(
        self,
        call: ToolCall,
        action: ExternalAction,
        attempt: ToolExecutionAttempt,
        run: Run,
        *,
        error: str,
        error_class: str,
        expected_generation: int,
    ) -> None:
        """Persist proven non-execution as FAILED; retry policy is deferred to D2."""
        self._assert_generation(expected_generation)
        if run.status is not RunStatus.FAILED:
            raise ValueError("definite side-effect failure requires FAILED Run")
        if call.status is not ToolCallStatus.EXECUTING:
            raise ValueError("definite side-effect failure requires EXECUTING ToolCall")
        if action.status is not ExternalActionStatus.EXECUTING:
            raise ValueError("definite side-effect failure requires EXECUTING ExternalAction")
        if action.current_attempt_id != attempt.id:
            raise ValueError("definite side-effect failure attempt is not current")

        async with self._sessions() as session, session.begin():
            run_row = await _lock_owned_run(
                session,
                run_id=call.run_id,
                expected_generation=expected_generation,
            )
            action_row = (
                await session.execute(
                    select(ExternalActionRow)
                    .where(
                        ExternalActionRow.id == action.id,
                        ExternalActionRow.run_id == call.run_id,
                    )
                    .with_for_update()
                )
            ).scalar_one()
            call_row = (
                await session.execute(
                    select(ToolCallRow)
                    .where(
                        ToolCallRow.id == call.id,
                        ToolCallRow.run_id == call.run_id,
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
                raise RuntimeError(
                    "side-effect definite failure lost current-attempt authorization"
                )

            attempt_row.status = ToolExecutionAttemptStatus.FAILED
            attempt_row.error = error
            attempt_row.error_class = error_class
            attempt_row.definite_not_executed = True
            attempt_row.outcome_reason = "SIDE_EFFECT_DEFINITE_NOT_EXECUTED"
            attempt_row.finished_at = func.clock_timestamp()
            call_row.status = ToolCallStatus.FAILED
            call_row.error = error
            action_row.status = ExternalActionStatus.FAILED
            action_row.current_attempt_id = None
            action_row.updated_at = func.clock_timestamp()
            run_row.status = RunStatus.FAILED
            run_row.failure_reason = run.failure_reason
            run_row.completed_at = func.clock_timestamp()
            run_row.owner_worker_id = None
            run_row.lease_expires_at = None

            seqs = list(await _allocate_event_sequences(session, call.run_id, 3))
            session.add_all(
                [
                    DomainEventRow(
                        id=uuid4(),
                        run_id=call.run_id,
                        sequence=seqs[0],
                        event_type=EventType.ACTION_FAILED.value,
                        payload={
                            "tool_call_id": str(call.id),
                            "external_action_id": str(action.id),
                            "operation_id": str(action.operation_id),
                            "attempt_id": str(attempt.id),
                            "attempt_number": attempt.attempt_number,
                            "error_class": error_class,
                            "definite_not_executed": True,
                        },
                    ),
                    DomainEventRow(
                        id=uuid4(),
                        run_id=call.run_id,
                        sequence=seqs[1],
                        event_type=EventType.TOOL_FAILED.value,
                        payload={
                            "tool_call_id": str(call.id),
                            "tool_name": call.tool_name,
                            "attempt_id": str(attempt.id),
                            "attempt_number": attempt.attempt_number,
                            "error_class": error_class,
                            "definite_not_executed": True,
                            "error": error,
                        },
                    ),
                    DomainEventRow(
                        id=uuid4(),
                        run_id=call.run_id,
                        sequence=seqs[2],
                        event_type=EventType.RUN_FAILED.value,
                        payload={"reason": run.failure_reason},
                    ),
                ]
            )
            await session.flush()

        attempt.fail(
            error,
            error_class=error_class,
            definite_not_executed=True,
            outcome_reason="SIDE_EFFECT_DEFINITE_NOT_EXECUTED",
        )
        call.fail(error)
        action.fail_definite_not_executed()

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
        self._assert_generation(expected_generation)
        if call.status is not ToolCallStatus.EXECUTING:
            raise ValueError("recovered READ call must be EXECUTING before persistence")
        async with self._sessions() as session, session.begin():
            run_row = await _lock_owned_run(
                session, run_id=call.run_id, expected_generation=expected_generation
            )
            state = await _lock_run_state(session, call.run_id)
            await _assert_deadline_not_expired(session, run_row)
            _assert_tool_budget(run_row, state)
            await _assert_no_started_model_invocations(session, call.run_id)
            await _assert_no_started_tool_attempts(session, call.run_id)
            result = await session.execute(
                update(ToolCallRow)
                .where(
                    ToolCallRow.id == call.id,
                    ToolCallRow.run_id == call.run_id,
                    ToolCallRow.status == ToolCallStatus.READY,
                    ToolCallRow.tool_version_id == call.tool_version_id,
                )
                .values(status=ToolCallStatus.EXECUTING, error=None)
            )
            if cast(CursorResult[Any], result).rowcount != 1:
                raise RuntimeError("recovered READ ToolCall is no longer READY")
            state.tool_attempts_used += 1
            state.state_version += 1
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

    async def record_recovered_read_blocked_and_fail_run(
        self,
        call: ToolCall,
        run: Run,
        *,
        expected_generation: int,
    ) -> None:
        self._assert_generation(expected_generation)
        if call.status is not ToolCallStatus.FAILED:
            raise ValueError("blocked recovered READ must be FAILED")
        if run.status is not RunStatus.FAILED:
            raise ValueError("blocked recovered READ requires FAILED run")
        async with self._sessions() as session, session.begin():
            row = await _lock_owned_run(
                session,
                run_id=run.id,
                expected_generation=expected_generation,
            )
            await _assert_no_started_tool_attempts(session, run.id)
            await _assert_no_started_model_invocations(session, run.id)
            result = await session.execute(
                update(ToolCallRow)
                .where(
                    ToolCallRow.id == call.id,
                    ToolCallRow.run_id == run.id,
                    ToolCallRow.status == ToolCallStatus.READY,
                )
                .values(status=ToolCallStatus.FAILED, error=call.error)
            )
            if cast(CursorResult[Any], result).rowcount != 1:
                raise RuntimeError("blocked recovered READ is no longer READY")
            row.status = RunStatus.FAILED
            row.failure_reason = run.failure_reason
            row.completed_at = func.clock_timestamp()
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
                        payload={"tool_call_id": str(call.id), "error": call.error},
                    ),
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[1],
                        event_type=EventType.RUN_FAILED.value,
                        payload={"reason": run.failure_reason},
                    ),
                ]
            )

    async def record_run_started(self, run: Run) -> None:
        raise RuntimeError("PostgreSQL Run must be atomically claimed before execution")

    async def begin_model_invocation(
        self,
        *,
        run_id: UUID,
        invocation_id: UUID,
        expected_generation: int,
    ) -> tuple[RunState, ModelInvocation]:
        """Atomically consume one turn and make the real model request durable.

        This closes the V0.4 crash window where turn_count could advance without
        any corresponding ModelInvocation ever being recorded.
        """
        self._assert_generation(expected_generation)
        async with self._sessions() as session, session.begin():
            run_row = await _lock_owned_run(
                session, run_id=run_id, expected_generation=expected_generation
            )
            await _assert_no_active_tool_calls(session, run_id)
            await _assert_no_unresolved_actions(session, run_id)
            await _assert_no_started_tool_attempts(session, run_id)
            await _assert_no_started_model_invocations(session, run_id)
            state = await _lock_run_state(session, run_id)
            await _assert_deadline_not_expired(session, run_row)
            _assert_model_budget(run_row, state)
            state.turn_count += 1
            state.model_invocations_used += 1
            state.state_version += 1
            invocation = ModelInvocation(invocation_id, run_id, state.turn_count)
            session.add(
                ModelInvocationRow(
                    id=invocation.id,
                    run_id=invocation.run_id,
                    turn=invocation.turn,
                    status=invocation.status.value,
                    outcome_type=None,
                    error=None,
                )
            )
            seq = next(iter(await _allocate_event_sequences(session, run_id, 1)))
            session.add(
                DomainEventRow(
                    id=uuid4(),
                    run_id=run_id,
                    sequence=seq,
                    event_type=EventType.MODEL_STARTED.value,
                    payload={"turn": invocation.turn, "invocation_id": str(invocation.id)},
                )
            )
            await session.flush()
            return run_state_from_row(state), invocation

    async def record_model_tool_started(
        self,
        invocation: ModelInvocation,
        proposal: ToolProposal,
        call: ToolCall,
        *,
        expected_generation: int,
    ) -> RunState:
        """Atomically persist the model decision and accepted READ ToolCall.

        A crash after this commit can recover from the EXECUTING ToolCall without
        asking the model to reconstruct an already-durable ToolProposal.
        """
        self._assert_generation(expected_generation)
        if invocation.status is not ModelInvocationStatus.COMPLETED:
            raise ValueError("model invocation must be COMPLETED before persistence")
        if call.status is not ToolCallStatus.EXECUTING:
            raise ValueError("accepted tool call must be EXECUTING before persistence")
        if call.tool_version_id is None:
            raise ValueError("accepted tool call must bind a tool version")

        async with self._sessions() as session, session.begin():
            run_row = await _lock_owned_run(
                session,
                run_id=invocation.run_id,
                expected_generation=expected_generation,
            )
            await _assert_no_active_tool_calls(session, call.run_id)
            state = await _lock_run_state(session, call.run_id)
            await _assert_deadline_not_expired(session, run_row)
            _assert_tool_budget(run_row, state)
            result = await session.execute(
                update(ModelInvocationRow)
                .where(
                    ModelInvocationRow.id == invocation.id,
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

            session.add(
                ToolProposalRow(
                    id=proposal.id,
                    run_id=proposal.run_id,
                    model_invocation_id=proposal.model_invocation_id,
                    tool_name=proposal.tool_name,
                    arguments=proposal.arguments,
                )
            )
            # ToolProposal is the durable parent intent for ToolCall. Because
            # these rows intentionally have no ORM relationship objects, flush
            # the parent explicitly while remaining inside this transaction.
            await session.flush()
            state.tool_call_count += 1
            state.tool_attempts_used += 1
            state.state_version += 1
            session.add(
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
            session.add_all(
                [
                    DomainEventRow(
                        id=uuid4(),
                        run_id=invocation.run_id,
                        sequence=seqs[0],
                        event_type=EventType.MODEL_COMPLETED.value,
                        payload={
                            "turn": invocation.turn,
                            "outcome_type": invocation.outcome_type,
                        },
                    ),
                    DomainEventRow(
                        id=uuid4(),
                        run_id=proposal.run_id,
                        sequence=seqs[1],
                        event_type=EventType.TOOL_PROPOSED.value,
                        payload={
                            "proposal_id": str(proposal.id),
                            "tool_name": proposal.tool_name,
                        },
                    ),
                    DomainEventRow(
                        id=uuid4(),
                        run_id=call.run_id,
                        sequence=seqs[2],
                        event_type=EventType.TOOL_STARTED.value,
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
            return run_state_from_row(state)

    async def record_model_side_effect_prepared(
        self,
        invocation: ModelInvocation,
        proposal: ToolProposal,
        call: ToolCall,
        snapshot: ActionSnapshot,
        action: ExternalAction,
        *,
        expected_generation: int,
    ) -> RunState:
        """Atomically commit side-effect intent without crossing the effect boundary."""
        self._assert_generation(expected_generation)
        if invocation.status is not ModelInvocationStatus.COMPLETED:
            raise ValueError("model invocation must be COMPLETED before persistence")
        if call.status is not ToolCallStatus.READY:
            raise ValueError("side-effect ToolCall must be READY before persistence")
        if call.tool_version_id is None:
            raise ValueError("side-effect ToolCall must bind a tool version")
        if action.status is not ExternalActionStatus.READY:
            raise ValueError("prepared ExternalAction must be READY")
        if snapshot.operation_id != action.operation_id:
            raise ValueError("ActionSnapshot and ExternalAction operation_id mismatch")
        if action.run_id != call.run_id:
            raise ValueError("ExternalAction run does not match ToolCall")
        if action.tool_call_id != call.id or action.action_snapshot_id != snapshot.id:
            raise ValueError("ExternalAction references do not match prepared intent")
        if snapshot.tool_version_id != call.tool_version_id:
            raise ValueError("ActionSnapshot ToolVersion does not match ToolCall")
        if snapshot.arguments != call.arguments or call.arguments != proposal.arguments:
            raise ValueError("prepared side-effect arguments diverged")

        async with self._sessions() as session, session.begin():
            run_row = await _lock_owned_run(
                session,
                run_id=call.run_id,
                expected_generation=expected_generation,
            )
            await _assert_no_active_tool_calls(session, call.run_id)
            await _assert_no_started_tool_attempts(session, call.run_id)
            state = await _lock_run_state(session, call.run_id)
            await _assert_deadline_not_expired(session, run_row)
            _assert_tool_budget(run_row, state)
            tool_version = await _lock_stage32_side_effect_tool_version(
                session,
                run=run_row,
                proposal=proposal,
                call=call,
            )
            if snapshot.effect_type is not tool_version.effect_type:
                raise ValueError("ActionSnapshot effect type does not match durable ToolVersion")
            if snapshot.credential_ref != tool_version.credential_ref:
                raise ValueError("ActionSnapshot credential_ref does not match durable ToolVersion")

            result = await session.execute(
                update(ModelInvocationRow)
                .where(
                    ModelInvocationRow.id == invocation.id,
                    ModelInvocationRow.run_id == call.run_id,
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

            session.add(
                ToolProposalRow(
                    id=proposal.id,
                    run_id=proposal.run_id,
                    model_invocation_id=proposal.model_invocation_id,
                    tool_name=proposal.tool_name,
                    arguments=proposal.arguments,
                )
            )
            await session.flush()

            state.tool_call_count += 1
            state.state_version += 1
            session.add(
                ToolCallRow(
                    id=call.id,
                    run_id=call.run_id,
                    proposal_id=call.proposal_id,
                    tool_version_id=call.tool_version_id,
                    tool_name=call.tool_name,
                    arguments=call.arguments,
                    status=ToolCallStatus.READY,
                )
            )
            session.add(
                ActionSnapshotRow(
                    id=snapshot.id,
                    format_version=snapshot.format_version,
                    operation_id=snapshot.operation_id,
                    tool_version_id=snapshot.tool_version_id,
                    effect_type=snapshot.effect_type,
                    credential_ref=snapshot.credential_ref,
                    arguments=snapshot.arguments,
                    canonical_json=snapshot.canonical_json,
                    digest=snapshot.digest,
                )
            )
            await session.flush()
            session.add(
                ExternalActionRow(
                    id=action.id,
                    run_id=action.run_id,
                    tool_call_id=action.tool_call_id,
                    action_snapshot_id=action.action_snapshot_id,
                    operation_id=action.operation_id,
                    status=ExternalActionStatus.READY,
                    current_attempt_id=None,
                )
            )

            seqs = list(await _allocate_event_sequences(session, call.run_id, 3))
            session.add_all(
                [
                    DomainEventRow(
                        id=uuid4(),
                        run_id=call.run_id,
                        sequence=seqs[0],
                        event_type=EventType.MODEL_COMPLETED.value,
                        payload={
                            "turn": invocation.turn,
                            "outcome_type": invocation.outcome_type,
                        },
                    ),
                    DomainEventRow(
                        id=uuid4(),
                        run_id=call.run_id,
                        sequence=seqs[1],
                        event_type=EventType.TOOL_PROPOSED.value,
                        payload={
                            "proposal_id": str(proposal.id),
                            "tool_name": proposal.tool_name,
                        },
                    ),
                    DomainEventRow(
                        id=uuid4(),
                        run_id=call.run_id,
                        sequence=seqs[2],
                        event_type=EventType.ACTION_PREPARED.value,
                        payload={
                            "tool_call_id": str(call.id),
                            "external_action_id": str(action.id),
                            "operation_id": str(action.operation_id),
                            "snapshot_digest": snapshot.digest,
                            "effect_type": snapshot.effect_type.value,
                        },
                    ),
                ]
            )
            await session.flush()
            return run_state_from_row(state)

    async def record_model_tool_denied_and_fail_run(
        self,
        invocation: ModelInvocation,
        proposal: ToolProposal,
        call: ToolCall,
        run: Run,
        *,
        expected_generation: int,
    ) -> None:
        """Persist a denied model-originated ToolCall instead of losing the intent."""
        self._assert_generation(expected_generation)
        if invocation.status is not ModelInvocationStatus.COMPLETED:
            raise ValueError("model invocation must be COMPLETED before persistence")
        if run.status is not RunStatus.FAILED:
            raise ValueError("denied tool persistence requires a FAILED run")
        if call.status is not ToolCallStatus.DENIED:
            raise ValueError("denied tool call must have DENIED status")

        async with self._sessions() as session, session.begin():
            row = await _lock_owned_run(
                session, run_id=run.id, expected_generation=expected_generation
            )
            await _assert_no_active_tool_calls(session, run.id)
            await _assert_deadline_not_expired(session, row)
            result = await session.execute(
                update(ModelInvocationRow)
                .where(
                    ModelInvocationRow.id == invocation.id,
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
            await _assert_no_started_model_invocations(session, run.id)

            session.add(
                ToolProposalRow(
                    id=proposal.id,
                    run_id=proposal.run_id,
                    model_invocation_id=proposal.model_invocation_id,
                    tool_name=proposal.tool_name,
                    arguments=proposal.arguments,
                )
            )
            state = await _lock_run_state(session, run.id)
            state.tool_call_count += 1
            state.state_version += 1
            session.add(
                ToolCallRow(
                    id=call.id,
                    run_id=call.run_id,
                    proposal_id=call.proposal_id,
                    tool_version_id=None,
                    tool_name=call.tool_name,
                    arguments=call.arguments,
                    status=call.status,
                    error=call.error,
                )
            )
            row.status = RunStatus.FAILED
            row.failure_reason = run.failure_reason
            row.completed_at = func.clock_timestamp()
            row.owner_worker_id = None
            row.lease_expires_at = None
            seqs = list(await _allocate_event_sequences(session, run.id, 4))
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
                        event_type=EventType.TOOL_PROPOSED.value,
                        payload={
                            "proposal_id": str(proposal.id),
                            "tool_name": proposal.tool_name,
                        },
                    ),
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[2],
                        event_type=EventType.TOOL_DENIED.value,
                        payload={
                            "tool_call_id": str(call.id),
                            "tool_name": call.tool_name,
                            "error": call.error,
                        },
                    ),
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[3],
                        event_type=EventType.RUN_FAILED.value,
                        payload={"reason": run.failure_reason},
                    ),
                ]
            )

    async def record_model_final_decision(
        self,
        invocation: ModelInvocation,
        run: Run,
        message: RunMessage,
        *,
        expected_generation: int,
    ) -> None:
        self._assert_generation(expected_generation)
        if invocation.status is not ModelInvocationStatus.COMPLETED:
            raise ValueError("model invocation must be COMPLETED before persistence")
        if run.status is not RunStatus.RUNNING:
            raise ValueError("final decision persistence requires a RUNNING run")
        async with self._sessions() as session, session.begin():
            row = await _lock_owned_run(
                session, run_id=run.id, expected_generation=expected_generation
            )
            await _assert_no_active_tool_calls(session, run.id)
            await _assert_deadline_not_expired(session, row)
            result = await session.execute(
                update(ModelInvocationRow)
                .where(
                    ModelInvocationRow.id == invocation.id,
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
            await _assert_no_started_model_invocations(session, run.id)
            row.status = RunStatus.COMPLETED
            row.final_output = message.content
            row.completed_at = func.clock_timestamp()
            row.owner_worker_id = None
            row.lease_expires_at = None
            message_seq = await _allocate_message_sequence(session, run.id)
            session.add(
                RunMessageRow(
                    id=uuid4(),
                    run_id=run.id,
                    sequence=message_seq,
                    role=message.role.value,
                    content=message.content,
                    source_id=message.source_id,
                )
            )
            seqs = list(await _allocate_event_sequences(session, run.id, 2))
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
                        event_type=EventType.RUN_COMPLETED.value,
                        payload={},
                    ),
                ]
            )

    async def record_model_result_discarded_and_fail_run(
        self,
        invocation: ModelInvocation,
        run: Run,
        reason: str,
        *,
        expected_generation: int,
    ) -> None:
        self._assert_generation(expected_generation)
        if invocation.status is not ModelInvocationStatus.COMPLETED:
            raise ValueError("discarded model result must be COMPLETED")
        if run.status is not RunStatus.FAILED:
            raise ValueError("discarded model result requires FAILED run")
        async with self._sessions() as session, session.begin():
            row = await _lock_owned_run(
                session,
                run_id=run.id,
                expected_generation=expected_generation,
            )
            await _assert_no_active_tool_calls(session, run.id)
            await _assert_no_started_tool_attempts(session, run.id)
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
            await _assert_no_started_model_invocations(session, run.id)
            row.status = RunStatus.FAILED
            row.failure_reason = run.failure_reason
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
                        event_type=EventType.RUN_FAILED.value,
                        payload={"reason": run.failure_reason},
                    ),
                ]
            )

    async def record_model_failed_and_fail_run(
        self,
        invocation: ModelInvocation,
        run: Run,
        *,
        expected_generation: int,
    ) -> None:
        self._assert_generation(expected_generation)
        if invocation.status is not ModelInvocationStatus.FAILED:
            raise ValueError("model invocation must be FAILED before persistence")
        if run.status is not RunStatus.FAILED:
            raise ValueError("model failure persistence requires a FAILED run")
        async with self._sessions() as session, session.begin():
            row = await _lock_owned_run(
                session, run_id=run.id, expected_generation=expected_generation
            )
            await _assert_no_active_tool_calls(session, run.id)
            result = await session.execute(
                update(ModelInvocationRow)
                .where(
                    ModelInvocationRow.id == invocation.id,
                    ModelInvocationRow.status == ModelInvocationStatus.STARTED.value,
                )
                .values(
                    status=invocation.status.value,
                    error=invocation.error,
                    completed_at=func.clock_timestamp(),
                )
            )
            if cast(CursorResult[Any], result).rowcount != 1:
                raise RuntimeError("model invocation no longer STARTED")
            await _assert_no_started_model_invocations(session, run.id)
            row.status = RunStatus.FAILED
            row.failure_reason = run.failure_reason
            row.completed_at = func.clock_timestamp()
            row.owner_worker_id = None
            row.lease_expires_at = None
            seqs = list(await _allocate_event_sequences(session, run.id, 2))
            session.add_all(
                [
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[0],
                        event_type=EventType.MODEL_FAILED.value,
                        payload={"turn": invocation.turn, "error": invocation.error},
                    ),
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run.id,
                        sequence=seqs[1],
                        event_type=EventType.RUN_FAILED.value,
                        payload={"reason": run.failure_reason},
                    ),
                ]
            )

    async def record_tool_succeeded(
        self,
        call: ToolCall,
        message: RunMessage,
        *,
        expected_generation: int,
    ) -> None:
        self._assert_generation(expected_generation)
        if call.status is not ToolCallStatus.SUCCEEDED:
            raise ValueError("tool success persistence requires a SUCCEEDED ToolCall")
        async with self._sessions() as session, session.begin():
            await _lock_owned_run(
                session, run_id=call.run_id, expected_generation=expected_generation
            )
            result = await session.execute(
                update(ToolCallRow)
                .where(
                    ToolCallRow.id == call.id,
                    ToolCallRow.status == ToolCallStatus.EXECUTING,
                )
                .values(status=ToolCallStatus.SUCCEEDED, result=call.result)
            )
            if cast(CursorResult[Any], result).rowcount != 1:
                raise RuntimeError("tool call no longer EXECUTING")
            attempt = await _lock_started_tool_attempt(session, call.id)
            attempt.status = ToolExecutionAttemptStatus.SUCCEEDED
            attempt.result = call.result
            attempt.finished_at = func.clock_timestamp()
            message_seq = await _allocate_message_sequence(session, call.run_id)
            session.add(
                RunMessageRow(
                    id=uuid4(),
                    run_id=call.run_id,
                    sequence=message_seq,
                    role=message.role.value,
                    content=message.content,
                    source_id=message.source_id,
                )
            )
            event_seq = next(iter(await _allocate_event_sequences(session, call.run_id, 1)))
            session.add(
                DomainEventRow(
                    id=uuid4(),
                    run_id=call.run_id,
                    sequence=event_seq,
                    event_type=EventType.TOOL_SUCCEEDED.value,
                    payload={
                        "tool_call_id": str(call.id),
                        "tool_name": call.tool_name,
                        "attempt_id": str(attempt.id),
                        "attempt_number": attempt.attempt_number,
                    },
                )
            )

    async def record_read_transient_failure(
        self,
        call: ToolCall,
        run: Run,
        *,
        max_attempts: int,
        initial_backoff_seconds: int,
        max_backoff_seconds: int,
        expected_generation: int,
    ) -> bool:
        self._assert_generation(expected_generation)
        if call.status is not ToolCallStatus.FAILED:
            raise ValueError("transient READ persistence requires FAILED ToolCall")
        if run.status is not RunStatus.RUNNING:
            raise ValueError("transient READ persistence requires RUNNING Run")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if initial_backoff_seconds < 0:
            raise ValueError("retry initial backoff cannot be negative")
        if max_backoff_seconds < initial_backoff_seconds:
            raise ValueError("retry max backoff cannot be below initial backoff")

        async with self._sessions() as session, session.begin():
            row = await _lock_owned_run(
                session, run_id=call.run_id, expected_generation=expected_generation
            )
            tool_call = (
                await session.execute(
                    select(ToolCallRow)
                    .where(
                        ToolCallRow.id == call.id,
                        ToolCallRow.run_id == call.run_id,
                        ToolCallRow.status == ToolCallStatus.EXECUTING,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if tool_call is None:
                raise RuntimeError("tool call no longer EXECUTING")
            attempt = await _lock_started_tool_attempt(session, call.id)
            state = await _lock_run_state(session, run.id)
            db_now = await _database_now(session)
            delay_seconds = min(
                initial_backoff_seconds * (2 ** (attempt.attempt_number - 1)),
                max_backoff_seconds,
            )
            due_at = db_now + timedelta(seconds=delay_seconds)

            attempt.status = ToolExecutionAttemptStatus.FAILED
            attempt.error = call.error
            attempt.error_class = "TRANSIENT"
            attempt.outcome_reason = "READ_TRANSIENT_FAILURE"
            attempt.definite_not_executed = True
            attempt.finished_at = db_now

            retry_allowed = (
                attempt.attempt_number < max_attempts
                and state.tool_attempts_used < row.max_tool_attempts
                and due_at < row.deadline_at
            )
            if retry_allowed:
                tool_call.status = ToolCallStatus.READY
                tool_call.error = call.error
                row.status = RunStatus.QUEUED
                row.queue_reason = QueueReason.RETRY
                row.available_at = due_at
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
                            event_type=EventType.TOOL_RETRY_SCHEDULED.value,
                            payload={
                                "tool_call_id": str(call.id),
                                "attempt_number": attempt.attempt_number,
                                "delay_seconds": delay_seconds,
                            },
                        ),
                    ]
                )
                run.status = RunStatus.QUEUED
                run.queue_reason = QueueReason.RETRY
                run.owner_worker_id = None
                run.lease_expires_at = None
                run.available_at = due_at
                return True

            if attempt.attempt_number >= max_attempts:
                failure_reason = "READ_RETRY_EXHAUSTED: versioned READ retry attempts exhausted"
            elif state.tool_attempts_used >= row.max_tool_attempts:
                failure_reason = "BUDGET_EXCEEDED: max_tool_attempts exhausted"
            else:
                failure_reason = "DEADLINE_EXCEEDED: READ retry due time reaches run deadline"

            tool_call.status = ToolCallStatus.FAILED
            tool_call.error = call.error
            row.status = RunStatus.FAILED
            row.failure_reason = failure_reason
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
                        event_type=EventType.RUN_FAILED.value,
                        payload={"reason": failure_reason},
                    ),
                ]
            )
            run.status = RunStatus.FAILED
            run.failure_reason = failure_reason
            run.completed_at = db_now
            return False

    async def record_tool_failed_and_fail_run(
        self,
        call: ToolCall,
        run: Run,
        *,
        expected_generation: int,
    ) -> None:
        self._assert_generation(expected_generation)
        if call.status is not ToolCallStatus.FAILED:
            raise ValueError("tool failure persistence requires a FAILED ToolCall")
        if run.status is not RunStatus.FAILED:
            raise ValueError("tool failure persistence requires a FAILED run")
        async with self._sessions() as session, session.begin():
            row = await _lock_owned_run(
                session, run_id=call.run_id, expected_generation=expected_generation
            )
            result = await session.execute(
                update(ToolCallRow)
                .where(
                    ToolCallRow.id == call.id,
                    ToolCallRow.status == ToolCallStatus.EXECUTING,
                )
                .values(status=ToolCallStatus.FAILED, error=call.error)
            )
            if cast(CursorResult[Any], result).rowcount != 1:
                raise RuntimeError("tool call no longer EXECUTING")
            attempt = await _lock_started_tool_attempt(session, call.id)
            attempt.status = ToolExecutionAttemptStatus.FAILED
            attempt.error = call.error
            attempt.error_class = "PERMANENT"
            attempt.outcome_reason = "READ_NON_RETRYABLE_FAILURE"
            attempt.definite_not_executed = True
            attempt.finished_at = func.clock_timestamp()
            await _assert_no_active_tool_calls(session, run.id)
            await session.flush()
            await _assert_no_started_tool_attempts(session, run.id)
            await _assert_no_started_model_invocations(session, run.id)
            row.status = RunStatus.FAILED
            row.failure_reason = run.failure_reason
            row.completed_at = func.clock_timestamp()
            row.owner_worker_id = None
            row.lease_expires_at = None
            seqs = list(await _allocate_event_sequences(session, call.run_id, 2))
            session.add_all(
                [
                    DomainEventRow(
                        id=uuid4(),
                        run_id=call.run_id,
                        sequence=seqs[0],
                        event_type=EventType.TOOL_FAILED.value,
                        payload={"tool_call_id": str(call.id), "error": call.error},
                    ),
                    DomainEventRow(
                        id=uuid4(),
                        run_id=call.run_id,
                        sequence=seqs[1],
                        event_type=EventType.RUN_FAILED.value,
                        payload={"reason": run.failure_reason},
                    ),
                ]
            )

    async def record_run_failed(self, run: Run, *, expected_generation: int) -> None:
        self._assert_generation(expected_generation)
        if run.status is not RunStatus.FAILED:
            raise ValueError("run failure persistence requires a FAILED run")
        async with self._sessions() as session, session.begin():
            row = await _lock_owned_run(
                session, run_id=run.id, expected_generation=expected_generation
            )
            await _assert_no_active_tool_calls(session, run.id)
            await _assert_no_started_tool_attempts(session, run.id)
            await _assert_no_started_model_invocations(session, run.id)
            row.status = RunStatus.FAILED
            row.failure_reason = run.failure_reason
            row.completed_at = func.clock_timestamp()
            row.owner_worker_id = None
            row.lease_expires_at = None
            seq = next(iter(await _allocate_event_sequences(session, run.id, 1)))
            session.add(
                DomainEventRow(
                    id=uuid4(),
                    run_id=run.id,
                    sequence=seq,
                    event_type=EventType.RUN_FAILED.value,
                    payload={"reason": run.failure_reason},
                )
            )

    async def record_run_yielded(
        self,
        run: Run,
        *,
        delay_seconds: int,
        expected_generation: int,
    ) -> None:
        self._assert_generation(expected_generation)
        if run.status is not RunStatus.QUEUED or run.queue_reason is not QueueReason.YIELD:
            raise ValueError("durable yield requires QUEUED/YIELD run")
        if delay_seconds < 0:
            raise ValueError("delay_seconds cannot be negative")
        async with self._sessions() as session, session.begin():
            row = await _lock_owned_run(
                session,
                run_id=run.id,
                expected_generation=expected_generation,
            )
            await _assert_no_active_tool_calls(session, run.id)
            await _assert_no_started_tool_attempts(session, run.id)
            await _assert_no_started_model_invocations(session, run.id)
            state = await _lock_run_state(session, run.id)
            await _assert_deadline_not_expired(session, row)
            _assert_model_budget(row, state)
            row.status = RunStatus.QUEUED
            row.queue_reason = QueueReason.YIELD
            row.available_at = func.clock_timestamp() + text(
                f"INTERVAL '{int(delay_seconds)} seconds'"
            )
            row.owner_worker_id = None
            row.lease_expires_at = None
            seq = next(iter(await _allocate_event_sequences(session, run.id, 1)))
            session.add(
                DomainEventRow(
                    id=uuid4(),
                    run_id=run.id,
                    sequence=seq,
                    event_type=EventType.RUN_YIELDED.value,
                    payload={"delay_seconds": delay_seconds},
                )
            )


class PostgresExecutionRecorderFactory:
    """Infrastructure adapter used by Worker composition roots."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    def __call__(self, *, run_id: UUID, generation: int) -> PostgresExecutionRecorder:
        return PostgresExecutionRecorder(
            self._sessions,
            run_id=run_id,
            generation=generation,
        )
