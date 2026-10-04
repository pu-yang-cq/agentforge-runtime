from __future__ import annotations

from hashlib import sha256
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, case, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentforge.application.errors import IdempotencyConflictError
from agentforge.application.ports import RuntimeStore
from agentforge.domain.enums import (
    EventType,
    ExternalActionStatus,
    MessageRole,
    ModelInvocationStatus,
    QueueReason,
    ReconciliationAttemptStatus,
    RunStatus,
    ToolCallStatus,
    ToolEffectType,
    ToolExecutionAttemptStatus,
)
from agentforge.domain.models import (
    DEFAULT_MAX_MODEL_INVOCATIONS,
    DEFAULT_MAX_TOOL_ATTEMPTS,
    DEFAULT_RUN_DEADLINE_SECONDS,
    AgentVersion,
    Run,
    RunState,
)
from agentforge.infrastructure.db.mappers import (
    agent_version_from_parts,
    run_from_row,
    run_state_from_row,
)
from agentforge.infrastructure.db.models import (
    AgentVersionRow,
    AgentVersionToolRow,
    DomainEventRow,
    ExternalActionRow,
    IdempotencyRecordRow,
    ModelInvocationRow,
    ReconciliationAttemptRow,
    RunCounterRow,
    RunMessageRow,
    RunRow,
    RunStateRow,
    ToolCallRow,
    ToolExecutionAttemptRow,
    ToolVersionRow,
)


def build_claim_candidate_stmt() -> Any:
    runnable = and_(
        RunRow.status == RunStatus.QUEUED,
        or_(RunRow.available_at.is_(None), RunRow.available_at <= func.clock_timestamp()),
    )
    recoverable = and_(
        RunRow.status == RunStatus.RUNNING,
        RunRow.lease_expires_at.is_not(None),
        RunRow.lease_expires_at < func.clock_timestamp(),
    )
    return (
        select(RunRow)
        .where(or_(runnable, recoverable))
        .order_by(
            case((RunRow.status == RunStatus.RUNNING, 0), else_=1),
            func.coalesce(RunRow.available_at, RunRow.created_at),
            RunRow.created_at,
            RunRow.id,
        )
        .limit(1)
        .with_for_update(skip_locked=True)
    )


def _lease_deadline_expr(lease_seconds: int) -> Any:
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")
    return func.clock_timestamp() + text(f"INTERVAL '{int(lease_seconds)} seconds'")


def _run_deadline_expr() -> Any:
    return func.clock_timestamp() + text(f"INTERVAL '{int(DEFAULT_RUN_DEADLINE_SECONDS)} seconds'")


async def _allocate_event_sequences(session: AsyncSession, run_id: UUID, count: int) -> range:
    result = await session.execute(
        update(RunCounterRow)
        .where(RunCounterRow.run_id == run_id)
        .values(event_sequence=RunCounterRow.event_sequence + count)
        .returning(RunCounterRow.event_sequence)
    )
    end = result.scalar_one()
    return range(end - count + 1, end + 1)


async def _close_orphaned_model_invocations_on_recovery(
    session: AsyncSession, run_id: UUID
) -> list[UUID]:
    rows = (
        (
            await session.execute(
                select(ModelInvocationRow)
                .where(
                    ModelInvocationRow.run_id == run_id,
                    ModelInvocationRow.status == ModelInvocationStatus.STARTED.value,
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    recovered: list[UUID] = []
    for invocation in rows:
        invocation.status = ModelInvocationStatus.FAILED.value
        invocation.error = (
            "previous executor lease expired before the model outcome was durably recorded"
        )
        invocation.completed_at = func.clock_timestamp()
        recovered.append(invocation.id)
    return recovered


async def _recover_orphaned_side_effect_attempts(
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


async def _recover_orphaned_reconciliation_attempts(
    session: AsyncSession,
    run_id: UUID,
) -> list[tuple[UUID, UUID]]:
    actions = (
        (
            await session.execute(
                select(ExternalActionRow)
                .where(
                    ExternalActionRow.run_id == run_id,
                    ExternalActionRow.status == ExternalActionStatus.RECONCILING,
                )
                .order_by(ExternalActionRow.id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    recovered: list[tuple[UUID, UUID]] = []
    for action in actions:
        attempt = (
            await session.execute(
                select(ReconciliationAttemptRow)
                .where(
                    ReconciliationAttemptRow.external_action_id == action.id,
                    ReconciliationAttemptRow.status == ReconciliationAttemptStatus.STARTED,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if attempt is None:
            continue
        attempt.status = ReconciliationAttemptStatus.FAILED
        attempt.error = "previous executor lease expired during read-only reconciliation"
        attempt.outcome_reason = "LEASE_LOST"
        attempt.finished_at = func.clock_timestamp()
        recovered.append((action.id, attempt.id))
    return recovered


async def _prepare_orphaned_read_calls_for_retry(session: AsyncSession, run_id: UUID) -> list[UUID]:
    """Return stale EXECUTING READ calls to READY for deterministic retry.

    Wave 1 supports READ tools only. A recovered READ is retried from the durable
    ToolCall rather than asking the model to reconstruct an already-persisted
    decision. If a future non-READ call appears here, fail closed.
    """
    rows = (
        await session.execute(
            select(ToolCallRow, ToolVersionRow.effect_type)
            .join(ToolVersionRow, ToolVersionRow.id == ToolCallRow.tool_version_id)
            .where(
                ToolCallRow.run_id == run_id,
                ToolCallRow.status == ToolCallStatus.EXECUTING,
            )
            .with_for_update()
        )
    ).all()
    recovered: list[UUID] = []
    for call, effect_type in rows:
        if effect_type != ToolEffectType.READ:
            raise RuntimeError(
                "cannot apply Wave-1 recovery semantics to a non-READ executing tool call"
            )
        attempt = (
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
    return recovered


class PostgresRuntimeStore(RuntimeStore):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def create_run(
        self,
        *,
        agent_version_id: UUID,
        input_text: str,
        idempotency_key: str,
        principal_scope: str,
    ) -> Run:
        run_id = uuid4()
        endpoint = "POST:/v1/runs"
        request_hash = sha256(f"{agent_version_id}\n{input_text}".encode()).hexdigest()
        async with self._sessions() as session, session.begin():
            inserted = await session.scalar(
                pg_insert(IdempotencyRecordRow)
                .values(
                    id=uuid4(),
                    principal_scope=principal_scope,
                    endpoint=endpoint,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                    resource_type="run",
                    resource_id=run_id,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        IdempotencyRecordRow.principal_scope,
                        IdempotencyRecordRow.endpoint,
                        IdempotencyRecordRow.idempotency_key,
                    ]
                )
                .returning(IdempotencyRecordRow.id)
            )
            if inserted is None:
                existing_record = (
                    await session.execute(
                        select(IdempotencyRecordRow).where(
                            IdempotencyRecordRow.principal_scope == principal_scope,
                            IdempotencyRecordRow.endpoint == endpoint,
                            IdempotencyRecordRow.idempotency_key == idempotency_key,
                        )
                    )
                ).scalar_one()
                if existing_record.request_hash != request_hash:
                    raise IdempotencyConflictError(
                        "idempotency key was already used with a different request"
                    )
                existing_run = await session.get(RunRow, existing_record.resource_id)
                if existing_run is None:
                    raise RuntimeError("idempotency record points to a missing run")
                return run_from_row(existing_run)

            exists = await session.scalar(
                select(AgentVersionRow.id).where(AgentVersionRow.id == agent_version_id)
            )
            if exists is None:
                raise KeyError(f"agent version not found: {agent_version_id}")

            row = RunRow(
                id=run_id,
                agent_version_id=agent_version_id,
                input_text=input_text,
                status=RunStatus.QUEUED,
                queue_reason=QueueReason.INITIAL,
                available_at=None,
                execution_generation=0,
                max_model_invocations=DEFAULT_MAX_MODEL_INVOCATIONS,
                max_tool_attempts=DEFAULT_MAX_TOOL_ATTEMPTS,
                deadline_at=_run_deadline_expr(),
            )
            session.add(row)
            await session.flush()
            session.add_all(
                [
                    RunStateRow(
                        run_id=run_id,
                        state_version=0,
                        turn_count=0,
                        tool_call_count=0,
                        model_invocations_used=0,
                        tool_attempts_used=0,
                    ),
                    RunCounterRow(run_id=run_id, event_sequence=2, message_sequence=1),
                    RunMessageRow(
                        id=uuid4(),
                        run_id=run_id,
                        sequence=1,
                        role=MessageRole.USER.value,
                        content=input_text,
                    ),
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run_id,
                        sequence=1,
                        event_type=EventType.RUN_CREATED.value,
                        payload={"agent_version_id": str(agent_version_id)},
                    ),
                    DomainEventRow(
                        id=uuid4(),
                        run_id=run_id,
                        sequence=2,
                        event_type=EventType.RUN_QUEUED.value,
                        payload={"queue_reason": QueueReason.INITIAL.value},
                    ),
                ]
            )
            await session.flush()
            await session.refresh(row)
            return run_from_row(row)

    async def get_run(self, run_id: UUID) -> Run | None:
        async with self._sessions() as session:
            row = await session.get(RunRow, run_id)
            return None if row is None else run_from_row(row)

    async def cancel_run(self, run_id: UUID) -> Run:
        async with self._sessions() as session, session.begin():
            row = (
                await session.execute(select(RunRow).where(RunRow.id == run_id).with_for_update())
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
                        .where(
                            ToolCallRow.run_id == run_id,
                            ToolCallRow.status == ToolCallStatus.READY,
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
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")

        async with self._sessions() as session, session.begin():
            row = (await session.execute(build_claim_candidate_stmt())).scalar_one_or_none()
            if row is None:
                return None

            was_recovery = row.status == RunStatus.RUNNING
            next_generation = row.execution_generation + 1
            lease_expression = _lease_deadline_expr(lease_seconds)
            await session.execute(
                update(RunRow)
                .where(RunRow.id == row.id)
                .values(
                    status=RunStatus.RUNNING,
                    queue_reason=None,
                    available_at=None,
                    execution_generation=next_generation,
                    owner_worker_id=worker_id,
                    lease_expires_at=lease_expression,
                    started_at=func.coalesce(RunRow.started_at, func.clock_timestamp()),
                )
            )
            recovered_model_ids = (
                await _close_orphaned_model_invocations_on_recovery(session, row.id)
                if was_recovery
                else []
            )
            recovered_side_effects = (
                await _recover_orphaned_side_effect_attempts(session, row.id)
                if was_recovery
                else []
            )
            recovered_reconciliations = (
                await _recover_orphaned_reconciliation_attempts(session, row.id)
                if was_recovery
                else []
            )
            recovered_call_ids = (
                await _prepare_orphaned_read_calls_for_retry(session, row.id)
                if was_recovery
                else []
            )
            base_event_count = 1 if was_recovery else 2
            sequences = list(
                await _allocate_event_sequences(
                    session,
                    row.id,
                    base_event_count
                    + len(recovered_model_ids)
                    + len(recovered_side_effects)
                    + len(recovered_reconciliations)
                    + len(recovered_call_ids),
                )
            )
            if was_recovery:
                session.add(
                    DomainEventRow(
                        id=uuid4(),
                        run_id=row.id,
                        sequence=sequences[0],
                        event_type=EventType.RUN_RECOVERED.value,
                        payload={"worker_id": worker_id, "generation": next_generation},
                    )
                )
                offset = 1
            else:
                session.add_all(
                    [
                        DomainEventRow(
                            id=uuid4(),
                            run_id=row.id,
                            sequence=sequences[0],
                            event_type=EventType.RUN_CLAIMED.value,
                            payload={"worker_id": worker_id, "generation": next_generation},
                        ),
                        DomainEventRow(
                            id=uuid4(),
                            run_id=row.id,
                            sequence=sequences[1],
                            event_type=EventType.RUN_STARTED.value,
                            payload={"worker_id": worker_id, "generation": next_generation},
                        ),
                    ]
                )
                offset = 2
            for invocation_id in recovered_model_ids:
                session.add(
                    DomainEventRow(
                        id=uuid4(),
                        run_id=row.id,
                        sequence=sequences[offset],
                        event_type=EventType.MODEL_FAILED.value,
                        payload={
                            "invocation_id": str(invocation_id),
                            "reason": "LEASE_LOST_MODEL_RESULT_NOT_DURABLE",
                        },
                    )
                )
                offset += 1
            for external_action_id, tool_call_id, attempt_id in recovered_side_effects:
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
            for external_action_id, attempt_id in recovered_reconciliations:
                session.add(
                    DomainEventRow(
                        id=uuid4(),
                        run_id=row.id,
                        sequence=sequences[offset],
                        event_type=EventType.RECONCILIATION_FAILED.value,
                        payload={
                            "external_action_id": str(external_action_id),
                            "attempt_id": str(attempt_id),
                            "reason": "LEASE_LOST",
                        },
                    )
                )
                offset += 1
            for tool_call_id in recovered_call_ids:
                session.add(
                    DomainEventRow(
                        id=uuid4(),
                        run_id=row.id,
                        sequence=sequences[offset],
                        event_type=EventType.TOOL_RETRY_READY.value,
                        payload={
                            "tool_call_id": str(tool_call_id),
                            "reason": "LEASE_LOST_READ_RETRY_READY",
                        },
                    )
                )
                offset += 1
            await session.flush()
            await session.refresh(row)
            return run_from_row(row)

    async def renew_lease(
        self,
        *,
        run_id: UUID,
        worker_id: str,
        expected_generation: int,
        lease_seconds: int,
    ) -> bool:
        async with self._sessions() as session, session.begin():
            result = await session.execute(
                update(RunRow)
                .where(
                    RunRow.id == run_id,
                    RunRow.status == RunStatus.RUNNING,
                    RunRow.execution_generation == expected_generation,
                    RunRow.owner_worker_id == worker_id,
                    RunRow.lease_expires_at.is_not(None),
                    RunRow.lease_expires_at > func.clock_timestamp(),
                )
                .values(lease_expires_at=_lease_deadline_expr(lease_seconds))
            )
            return cast(CursorResult[Any], result).rowcount == 1

    async def load_run_state(self, run_id: UUID) -> RunState:
        async with self._sessions() as session:
            row = await session.get(RunStateRow, run_id)
            if row is None:
                raise KeyError(f"run state not found: {run_id}")
            return run_state_from_row(row)

    async def load_agent_version(self, agent_version_id: UUID) -> AgentVersion:
        async with self._sessions() as session:
            version = await session.get(AgentVersionRow, agent_version_id)
            if version is None:
                raise KeyError(f"agent version not found: {agent_version_id}")
            rows = (
                await session.execute(
                    select(
                        AgentVersionToolRow.tool_version_id,
                        AgentVersionToolRow.tool_alias,
                        ToolVersionRow.read_retry_max_attempts,
                        ToolVersionRow.read_retry_initial_backoff_seconds,
                        ToolVersionRow.read_retry_max_backoff_seconds,
                        ToolVersionRow.effect_type,
                        ToolVersionRow.approval_required,
                        ToolVersionRow.allow_no_approval_execution,
                        ToolVersionRow.credential_ref,
                        ToolVersionRow.idempotency_supported,
                        ToolVersionRow.reconciliation_mode,
                        ToolVersionRow.side_effect_retry_max_attempts,
                        ToolVersionRow.side_effect_retry_initial_backoff_seconds,
                        ToolVersionRow.side_effect_retry_max_backoff_seconds,
                        ToolVersionRow.reconciliation_max_attempts,
                        ToolVersionRow.reconciliation_initial_backoff_seconds,
                        ToolVersionRow.reconciliation_max_backoff_seconds,
                    )
                    .join(
                        ToolVersionRow,
                        ToolVersionRow.id == AgentVersionToolRow.tool_version_id,
                    )
                    .where(AgentVersionToolRow.agent_version_id == agent_version_id)
                    .order_by(AgentVersionToolRow.tool_alias)
                )
            ).all()
            return agent_version_from_parts(
                version_id=version.id,
                agent_id=version.agent_id,
                version_number=version.version_number,
                instructions=version.instructions,
                bindings=[
                    (
                        tool_version_id,
                        alias,
                        retry_max_attempts,
                        retry_initial_backoff,
                        retry_max_backoff,
                        effect_type,
                        approval_required,
                        allow_no_approval_execution,
                        credential_ref,
                        idempotency_supported,
                        reconciliation_mode,
                        side_effect_retry_max_attempts,
                        side_effect_retry_initial_backoff_seconds,
                        side_effect_retry_max_backoff_seconds,
                        reconciliation_max_attempts,
                        reconciliation_initial_backoff_seconds,
                        reconciliation_max_backoff_seconds,
                    )
                    for (
                        tool_version_id,
                        alias,
                        retry_max_attempts,
                        retry_initial_backoff,
                        retry_max_backoff,
                        effect_type,
                        approval_required,
                        allow_no_approval_execution,
                        credential_ref,
                        idempotency_supported,
                        reconciliation_mode,
                        side_effect_retry_max_attempts,
                        side_effect_retry_initial_backoff_seconds,
                        side_effect_retry_max_backoff_seconds,
                        reconciliation_max_attempts,
                        reconciliation_initial_backoff_seconds,
                        reconciliation_max_backoff_seconds,
                    ) in rows
                ],
            )
