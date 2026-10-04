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
    MessageRole,
    ModelInvocationStatus,
    QueueReason,
    RunStatus,
    ToolCallStatus,
    ToolEffectType,
    ToolExecutionAttemptStatus,
)
from agentforge.domain.models import AgentVersion, Run, RunState
from agentforge.infrastructure.db.mappers import (
    agent_version_from_parts,
    run_from_row,
    run_state_from_row,
)
from agentforge.infrastructure.db.models import (
    AgentVersionRow,
    AgentVersionToolRow,
    DomainEventRow,
    IdempotencyRecordRow,
    ModelInvocationRow,
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
            )
            session.add(row)
            await session.flush()
            session.add_all(
                [
                    RunStateRow(run_id=run_id, state_version=0, turn_count=0, tool_call_count=0),
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
                    base_event_count + len(recovered_model_ids) + len(recovered_call_ids),
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
                bindings=[(tool_version_id, alias) for tool_version_id, alias in rows],
            )
