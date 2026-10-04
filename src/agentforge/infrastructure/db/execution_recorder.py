from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import Select

from agentforge.application.errors import StaleExecutorError
from agentforge.application.ports import ExecutionRecorder
from agentforge.domain.enums import (
    EventType,
    ModelInvocationStatus,
    RunStatus,
    ToolCallStatus,
)
from agentforge.domain.models import (
    ModelInvocation,
    Run,
    RunMessage,
    RunState,
    ToolCall,
    ToolProposal,
)
from agentforge.infrastructure.db.mappers import (
    message_from_row,
    run_state_from_row,
    tool_call_from_row,
)
from agentforge.infrastructure.db.models import (
    DomainEventRow,
    ModelInvocationRow,
    RunCounterRow,
    RunMessageRow,
    RunRow,
    RunStateRow,
    ToolCallRow,
    ToolProposalRow,
)
from agentforge.infrastructure.db.runtime_store import _allocate_event_sequences


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
                        .where(
                            ToolCallRow.run_id == run_id,
                            ToolCallRow.status == ToolCallStatus.READY,
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
            await _lock_owned_run(
                session, run_id=call.run_id, expected_generation=expected_generation
            )
            await _assert_no_started_model_invocations(session, call.run_id)
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
            await _lock_owned_run(session, run_id=run_id, expected_generation=expected_generation)
            await _assert_no_active_tool_calls(session, run_id)
            await _assert_no_started_model_invocations(session, run_id)
            state = await _lock_run_state(session, run_id)
            state.turn_count += 1
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
            await _lock_owned_run(
                session,
                run_id=invocation.run_id,
                expected_generation=expected_generation,
            )
            await _assert_no_active_tool_calls(session, call.run_id)
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
            state = await _lock_run_state(session, call.run_id)
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
                    status=call.status,
                )
            )
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
                        payload={"tool_call_id": str(call.id), "tool_name": call.tool_name},
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
        if run.status is not RunStatus.COMPLETED:
            raise ValueError("final decision persistence requires a COMPLETED run")
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
                    outcome_type=invocation.outcome_type,
                    completed_at=func.clock_timestamp(),
                )
            )
            if cast(CursorResult[Any], result).rowcount != 1:
                raise RuntimeError("model invocation no longer STARTED")
            await _assert_no_started_model_invocations(session, run.id)
            row.status = RunStatus.COMPLETED
            row.final_output = run.final_output
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
                    payload={"tool_call_id": str(call.id), "tool_name": call.tool_name},
                )
            )

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
            await _assert_no_active_tool_calls(session, run.id)
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
