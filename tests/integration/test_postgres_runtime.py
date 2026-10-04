# ruff: noqa: E402

import asyncio
import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text

REQUIRE_POSTGRES = os.getenv("AGENTFORGE_REQUIRE_POSTGRES_INTEGRATION") == "1"
try:
    import psycopg  # noqa: F401
except ImportError as exc:
    if REQUIRE_POSTGRES:
        raise RuntimeError("psycopg is required for the Stage 3.1 acceptance gate") from exc
    pytest.skip("psycopg is not installed", allow_module_level=True)

DATABASE_URL = os.getenv("AGENTFORGE_TEST_DATABASE_URL")
if not DATABASE_URL:
    if REQUIRE_POSTGRES:
        raise RuntimeError(
            "AGENTFORGE_TEST_DATABASE_URL is required for the Stage 3.1 acceptance gate"
        )
    pytest.skip(
        "set AGENTFORGE_TEST_DATABASE_URL to a PostgreSQL 18 test database",
        allow_module_level=True,
    )

from agentforge.application.errors import IdempotencyConflictError, StaleExecutorError
from agentforge.application.worker import CoreWorker
from agentforge.demo import (
    DEMO_AGENT_ID,
    DEMO_AGENT_VERSION_ID,
    DEMO_TOOL_ID,
    DEMO_TOOL_VERSION_ID,
    build_demo_model,
    build_demo_registry,
)
from agentforge.domain.enums import EventType, RunStatus, ToolCallStatus, ToolEffectType
from agentforge.domain.models import ToolProposal
from agentforge.infrastructure.db.execution_recorder import (
    PostgresExecutionRecorder,
    PostgresExecutionRecorderFactory,
)
from agentforge.infrastructure.db.models import (
    AgentRow,
    AgentVersionRow,
    AgentVersionToolRow,
    DomainEventRow,
    RunMessageRow,
    ToolCallRow,
    ToolDefinitionRow,
    ToolVersionRow,
)
from agentforge.infrastructure.db.runtime_store import PostgresRuntimeStore
from agentforge.infrastructure.db.session import create_engine, create_session_factory
from agentforge.runtime.fake_model import FinalStep, ScriptedFakeModel, ToolStep
from agentforge.runtime.tool_coordinator import ToolCoordinator


def reset_schema() -> None:
    config = Config("alembic.ini")
    # This suite is intentionally destructive. Mark the test URL as an explicit
    # Alembic caller override so migrations/env.py cannot replace it with an
    # ambient AGENTFORGE_DATABASE_URL that might point at non-test data.
    config.attributes["agentforge_explicit_database_url"] = DATABASE_URL
    config.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.downgrade(config, "base")
    command.upgrade(config, "head")


async def seed_demo(session_factory) -> None:
    async with session_factory() as session, session.begin():
        session.add_all(
            [
                AgentRow(
                    id=DEMO_AGENT_ID,
                    name="wave1-demo-agent",
                    description="test agent",
                ),
                ToolDefinitionRow(
                    id=DEMO_TOOL_ID,
                    name="echo_read",
                    description="read tool",
                ),
            ]
        )
        await session.flush()

        session.add_all(
            [
                ToolVersionRow(
                    id=DEMO_TOOL_VERSION_ID,
                    tool_id=DEMO_TOOL_ID,
                    version_number=1,
                    input_schema={"type": "object"},
                    effect_type=ToolEffectType.READ,
                    implementation_ref="agentforge.demo:echo_read",
                ),
                AgentVersionRow(
                    id=DEMO_AGENT_VERSION_ID,
                    agent_id=DEMO_AGENT_ID,
                    version_number=1,
                    instructions="Call echo_read once, then finish.",
                ),
            ]
        )
        await session.flush()

        session.add(
            AgentVersionToolRow(
                agent_version_id=DEMO_AGENT_VERSION_ID,
                tool_version_id=DEMO_TOOL_VERSION_ID,
                tool_alias="echo_read",
            )
        )


@pytest.mark.asyncio
async def test_validation_environment_uses_python_314_and_postgresql_18() -> None:
    import sys

    assert sys.version_info[:2] == (3, 14)
    engine = create_engine(DATABASE_URL)
    async with engine.connect() as connection:
        version_num = int(
            await connection.scalar(text("SELECT current_setting('server_version_num')"))
        )
    assert 180000 <= version_num < 190000
    await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_durable_core_end_to_end_and_idempotency() -> None:
    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store = PostgresRuntimeStore(sessions)

    run = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="hello durable runtime",
        idempotency_key="integration-create-1",
        principal_scope="test-user",
    )
    duplicate = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="hello durable runtime",
        idempotency_key="integration-create-1",
        principal_scope="test-user",
    )
    assert duplicate.id == run.id
    with pytest.raises(IdempotencyConflictError):
        await store.create_run(
            agent_version_id=DEMO_AGENT_VERSION_ID,
            input_text="different request",
            idempotency_key="integration-create-1",
            principal_scope="test-user",
        )

    # A fresh engine/session factory simulates a new process seeing the queued durable Run.
    await engine.dispose()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    restarted_store = PostgresRuntimeStore(sessions)
    worker = CoreWorker(
        runtime_store=restarted_store,
        recorder_factory=PostgresExecutionRecorderFactory(sessions),
        tool_registry=build_demo_registry(),
        model_factory=build_demo_model,
        worker_id="worker-integration",
        lease_seconds=30,
    )
    assert await worker.run_once() is True

    completed = await restarted_store.get_run(run.id)
    assert completed is not None
    assert completed.status is RunStatus.COMPLETED
    assert completed.execution_generation == 1
    assert completed.final_output is not None

    async with sessions() as session:
        event_count = await session.scalar(
            select(func.count()).select_from(DomainEventRow).where(DomainEventRow.run_id == run.id)
        )
        message_count = await session.scalar(
            select(func.count()).select_from(RunMessageRow).where(RunMessageRow.run_id == run.id)
        )
        tool_call_count = await session.scalar(
            select(func.count()).select_from(ToolCallRow).where(ToolCallRow.run_id == run.id)
        )
        event_rows = (
            await session.execute(
                select(DomainEventRow.sequence, DomainEventRow.event_type)
                .where(DomainEventRow.run_id == run.id)
                .order_by(DomainEventRow.sequence)
            )
        ).all()
        message_sequences = (
            (
                await session.execute(
                    select(RunMessageRow.sequence)
                    .where(RunMessageRow.run_id == run.id)
                    .order_by(RunMessageRow.sequence)
                )
            )
            .scalars()
            .all()
        )
        event_types = [event_type for _, event_type in event_rows]
        event_sequences = [sequence for sequence, _ in event_rows]
    assert event_count >= 8
    assert message_count == 3
    assert tool_call_count == 1
    assert EventType.RUN_CLAIMED.value in event_types
    assert EventType.RUN_STARTED.value in event_types
    assert event_sequences == list(range(1, len(event_sequences) + 1))
    assert message_sequences == list(range(1, len(message_sequences) + 1))

    await engine.dispose()


@pytest.mark.asyncio
async def test_unbound_model_tool_request_is_durably_denied() -> None:
    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store = PostgresRuntimeStore(sessions)
    run = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="request an unbound tool",
        idempotency_key="integration-denied-tool-1",
        principal_scope="test-user",
    )

    worker = CoreWorker(
        runtime_store=store,
        recorder_factory=PostgresExecutionRecorderFactory(sessions),
        tool_registry=build_demo_registry(),
        model_factory=lambda _: ScriptedFakeModel(
            [ToolStep("delete_customer", {"customer_id": "c-1"})]
        ),
        worker_id="worker-denied-tool",
        lease_seconds=30,
    )
    assert await worker.run_once() is True

    failed = await store.get_run(run.id)
    assert failed is not None
    assert failed.status is RunStatus.FAILED

    async with sessions() as session:
        calls = (
            (await session.execute(select(ToolCallRow).where(ToolCallRow.run_id == run.id)))
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
    assert calls[0].status is ToolCallStatus.DENIED
    assert calls[0].tool_version_id is None
    assert EventType.TOOL_DENIED.value in event_types

    await engine.dispose()


@pytest.mark.asyncio
async def test_two_workers_cannot_claim_the_same_queued_run() -> None:
    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store_a = PostgresRuntimeStore(sessions)
    store_b = PostgresRuntimeStore(sessions)
    run = await store_a.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="claim me once",
        idempotency_key="integration-claim-1",
        principal_scope="test-user",
    )

    results = await asyncio.gather(
        store_a.claim_next_run(worker_id="worker-a", lease_seconds=30),
        store_b.claim_next_run(worker_id="worker-b", lease_seconds=30),
    )
    claimed = [item for item in results if item is not None]
    assert len(claimed) == 1
    assert claimed[0].id == run.id
    assert claimed[0].execution_generation == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_expired_lease_takeover_fences_stale_generation() -> None:
    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store = PostgresRuntimeStore(sessions)
    run = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="lease takeover",
        idempotency_key="integration-takeover-1",
        principal_scope="test-user",
    )

    claimed_a = await store.claim_next_run(worker_id="worker-a", lease_seconds=1)
    assert claimed_a is not None
    assert claimed_a.id == run.id
    assert claimed_a.execution_generation == 1
    recorder_a = PostgresExecutionRecorder(
        sessions, run_id=run.id, generation=claimed_a.execution_generation
    )

    await asyncio.sleep(1.2)

    # Lease expiry alone revokes progression authority, even before another
    # worker increments the generation.
    with pytest.raises(StaleExecutorError):
        await recorder_a.begin_model_invocation(
            run_id=run.id, invocation_id=uuid4(), expected_generation=1
        )

    claimed_b = await store.claim_next_run(worker_id="worker-b", lease_seconds=30)
    assert claimed_b is not None
    assert claimed_b.id == run.id
    assert claimed_b.execution_generation == 2

    # After takeover the stale generation remains fenced as a second layer.
    with pytest.raises(StaleExecutorError):
        await recorder_a.begin_model_invocation(
            run_id=run.id, invocation_id=uuid4(), expected_generation=1
        )

    recorder_b = PostgresExecutionRecorder(
        sessions, run_id=run.id, generation=claimed_b.execution_generation
    )
    state, _ = await recorder_b.begin_model_invocation(
        run_id=run.id, invocation_id=uuid4(), expected_generation=2
    )
    assert state.turn_count == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_takeover_prepares_orphaned_read_for_deterministic_retry() -> None:
    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store = PostgresRuntimeStore(sessions)
    run = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="orphan a read call",
        idempotency_key="integration-orphan-read-1",
        principal_scope="test-user",
    )
    claimed_a = await store.claim_next_run(worker_id="worker-a", lease_seconds=2)
    assert claimed_a is not None

    recorder_a = PostgresExecutionRecorder(
        sessions, run_id=run.id, generation=claimed_a.execution_generation
    )
    state, invocation = await recorder_a.begin_model_invocation(
        run_id=run.id, invocation_id=uuid4(), expected_generation=1
    )
    assert invocation.turn == state.turn_count
    invocation.complete("TOOL_PROPOSAL")
    proposal = ToolProposal.create(
        run_id=run.id,
        model_invocation_id=invocation.id,
        tool_name="echo_read",
        arguments={"text": "hello"},
    )
    agent_version = await store.load_agent_version(DEMO_AGENT_VERSION_ID)
    prepared = ToolCoordinator(build_demo_registry()).prepare_read(
        proposal=proposal, agent_version=agent_version
    )
    await recorder_a.record_model_tool_started(
        invocation, proposal, prepared.call, expected_generation=1
    )

    await asyncio.sleep(2.2)
    claimed_b = await store.claim_next_run(worker_id="worker-b", lease_seconds=30)
    assert claimed_b is not None
    assert claimed_b.execution_generation == 2

    async with sessions() as session:
        call_row = await session.get(ToolCallRow, prepared.call.id)
        assert call_row is not None
        assert call_row.status is ToolCallStatus.READY
        assert call_row.error is not None
        assert "deterministic READ retry" in call_row.error
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
    assert EventType.RUN_RECOVERED.value in event_types
    assert EventType.TOOL_RETRY_READY.value in event_types

    await engine.dispose()


@pytest.mark.asyncio
async def test_late_model_result_cannot_commit_after_lease_expiry() -> None:
    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store = PostgresRuntimeStore(sessions)
    run = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="late model result",
        idempotency_key="integration-late-model-1",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="worker-a", lease_seconds=1)
    assert claimed is not None
    recorder = PostgresExecutionRecorder(
        sessions, run_id=run.id, generation=claimed.execution_generation
    )
    state, invocation = await recorder.begin_model_invocation(
        run_id=run.id, invocation_id=uuid4(), expected_generation=1
    )
    assert invocation.turn == state.turn_count
    invocation.complete("TOOL_PROPOSAL")
    proposal = ToolProposal.create(
        run_id=run.id,
        model_invocation_id=invocation.id,
        tool_name="echo_read",
        arguments={"text": "late"},
    )
    agent_version = await store.load_agent_version(DEMO_AGENT_VERSION_ID)
    prepared = ToolCoordinator(build_demo_registry()).prepare_read(
        proposal=proposal, agent_version=agent_version
    )
    await asyncio.sleep(1.2)

    with pytest.raises(StaleExecutorError):
        await recorder.record_model_tool_started(
            invocation, proposal, prepared.call, expected_generation=1
        )

    from agentforge.infrastructure.db.models import ModelInvocationRow, ToolCallRow, ToolProposalRow

    async with sessions() as session:
        invocation_row = await session.get(ModelInvocationRow, invocation.id)
        assert invocation_row is not None
        assert invocation_row.status == "STARTED"
        proposal_count = await session.scalar(
            select(func.count())
            .select_from(ToolProposalRow)
            .where(ToolProposalRow.run_id == run.id)
        )
        tool_call_count = await session.scalar(
            select(func.count()).select_from(ToolCallRow).where(ToolCallRow.run_id == run.id)
        )
    assert proposal_count == 0
    assert tool_call_count == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_takeover_terminalizes_orphaned_started_model_invocation() -> None:
    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store = PostgresRuntimeStore(sessions)
    run = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="orphan a model call",
        idempotency_key="integration-orphan-model-1",
        principal_scope="test-user",
    )
    claimed_a = await store.claim_next_run(worker_id="worker-a", lease_seconds=1)
    assert claimed_a is not None
    recorder_a = PostgresExecutionRecorder(
        sessions, run_id=run.id, generation=claimed_a.execution_generation
    )
    state, invocation = await recorder_a.begin_model_invocation(
        run_id=run.id, invocation_id=uuid4(), expected_generation=1
    )
    assert invocation.turn == state.turn_count

    await asyncio.sleep(1.2)
    claimed_b = await store.claim_next_run(worker_id="worker-b", lease_seconds=30)
    assert claimed_b is not None
    assert claimed_b.execution_generation == 2

    from agentforge.infrastructure.db.models import ModelInvocationRow

    async with sessions() as session:
        row = await session.get(ModelInvocationRow, invocation.id)
        assert row is not None
        assert row.status == "FAILED"
        assert row.error is not None
        assert "lease expired" in row.error
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
    assert EventType.MODEL_STARTED.value in event_types
    assert EventType.MODEL_FAILED.value in event_types
    assert EventType.RUN_RECOVERED.value in event_types

    await engine.dispose()


@pytest.mark.asyncio
async def test_worker_restart_after_expired_claim_recovers_and_completes() -> None:
    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store = PostgresRuntimeStore(sessions)
    run = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="recover after worker process disappears",
        idempotency_key="integration-restart-1",
        principal_scope="test-user",
    )
    claimed_a = await store.claim_next_run(worker_id="dead-worker", lease_seconds=1)
    assert claimed_a is not None
    assert claimed_a.execution_generation == 1

    # The first process disappears without progressing the Run or releasing its lease.
    await asyncio.sleep(1.2)
    await engine.dispose()

    restarted_engine = create_engine(DATABASE_URL)
    restarted_sessions = create_session_factory(restarted_engine)
    restarted_store = PostgresRuntimeStore(restarted_sessions)
    worker_b = CoreWorker(
        runtime_store=restarted_store,
        recorder_factory=PostgresExecutionRecorderFactory(restarted_sessions),
        tool_registry=build_demo_registry(),
        model_factory=build_demo_model,
        worker_id="replacement-worker",
        lease_seconds=30,
    )
    assert await worker_b.run_once() is True

    completed = await restarted_store.get_run(run.id)
    assert completed is not None
    assert completed.status is RunStatus.COMPLETED
    assert completed.execution_generation == 2

    async with restarted_sessions() as session:
        recovered_count = await session.scalar(
            select(func.count())
            .select_from(DomainEventRow)
            .where(
                DomainEventRow.run_id == run.id,
                DomainEventRow.event_type == EventType.RUN_RECOVERED.value,
            )
        )
    assert recovered_count == 1

    await restarted_engine.dispose()


@pytest.mark.asyncio
async def test_recovered_read_is_retried_before_model_and_reuses_same_tool_call() -> None:
    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store = PostgresRuntimeStore(sessions)
    run = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="deterministic retry after crash",
        idempotency_key="integration-read-retry-1",
        principal_scope="test-user",
    )
    claimed_a = await store.claim_next_run(worker_id="worker-a", lease_seconds=1)
    assert claimed_a is not None
    recorder_a = PostgresExecutionRecorder(
        sessions, run_id=run.id, generation=claimed_a.execution_generation
    )
    state, invocation = await recorder_a.begin_model_invocation(
        run_id=run.id, invocation_id=uuid4(), expected_generation=1
    )
    invocation.complete("TOOL_PROPOSAL")
    proposal = ToolProposal.create(
        run_id=run.id,
        model_invocation_id=invocation.id,
        tool_name="echo_read",
        arguments={"text": "same-durable-intent"},
    )
    agent_version = await store.load_agent_version(DEMO_AGENT_VERSION_ID)
    prepared = ToolCoordinator(build_demo_registry()).prepare_read(
        proposal=proposal, agent_version=agent_version
    )
    await recorder_a.record_model_tool_started(
        invocation, proposal, prepared.call, expected_generation=1
    )
    original_call_id = prepared.call.id

    await asyncio.sleep(1.2)

    # Worker B's model has only a FinalStep. If Runtime asks the model before
    # replaying the durable READ ToolCall, this test cannot produce the required
    # Tool observation and will expose the ordering bug.
    worker_b = CoreWorker(
        runtime_store=store,
        recorder_factory=PostgresExecutionRecorderFactory(sessions),
        tool_registry=build_demo_registry(),
        model_factory=lambda _: ScriptedFakeModel(
            [FinalStep("completed after deterministic read recovery")]
        ),
        worker_id="worker-b",
        lease_seconds=30,
    )
    assert await worker_b.run_once() is True

    completed = await store.get_run(run.id)
    assert completed is not None
    assert completed.status is RunStatus.COMPLETED
    assert completed.execution_generation == 2

    async with sessions() as session:
        calls = (
            (await session.execute(select(ToolCallRow).where(ToolCallRow.run_id == run.id)))
            .scalars()
            .all()
        )
        messages = (
            (
                await session.execute(
                    select(RunMessageRow)
                    .where(RunMessageRow.run_id == run.id)
                    .order_by(RunMessageRow.sequence)
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
    assert calls[0].status is ToolCallStatus.SUCCEEDED
    assert sum(1 for message in messages if message.role == "TOOL") == 1
    assert EventType.TOOL_RETRY_READY.value in event_types
    assert event_types.count(EventType.TOOL_STARTED.value) == 2
    assert EventType.TOOL_SUCCEEDED.value in event_types

    await engine.dispose()


@pytest.mark.asyncio
async def test_database_rejects_multiple_active_tool_calls_for_one_run() -> None:
    from sqlalchemy.exc import IntegrityError

    from agentforge.infrastructure.db.models import ToolProposalRow

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store = PostgresRuntimeStore(sessions)
    run = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="enforce single active read",
        idempotency_key="integration-one-active-tool-1",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="worker-a", lease_seconds=30)
    assert claimed is not None
    recorder = PostgresExecutionRecorder(
        sessions, run_id=run.id, generation=claimed.execution_generation
    )
    _, invocation = await recorder.begin_model_invocation(
        run_id=run.id, invocation_id=uuid4(), expected_generation=1
    )
    invocation.complete("TOOL_PROPOSAL")
    proposal = ToolProposal.create(
        run_id=run.id,
        model_invocation_id=invocation.id,
        tool_name="echo_read",
        arguments={"text": "first"},
    )
    agent_version = await store.load_agent_version(DEMO_AGENT_VERSION_ID)
    first = ToolCoordinator(build_demo_registry()).prepare_read(
        proposal=proposal, agent_version=agent_version
    )
    await recorder.record_model_tool_started(
        invocation, proposal, first.call, expected_generation=1
    )

    second_proposal_id = uuid4()
    async with sessions() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(
                    ToolProposalRow(
                        id=second_proposal_id,
                        run_id=run.id,
                        model_invocation_id=invocation.id,
                        tool_name="echo_read",
                        arguments={"text": "second"},
                    )
                )
                session.add(
                    ToolCallRow(
                        id=uuid4(),
                        run_id=run.id,
                        proposal_id=second_proposal_id,
                        tool_version_id=DEMO_TOOL_VERSION_ID,
                        tool_name="echo_read",
                        arguments={"text": "second"},
                        status=ToolCallStatus.READY,
                    )
                )
                await session.flush()

    async with sessions() as session:
        active_count = await session.scalar(
            select(func.count())
            .select_from(ToolCallRow)
            .where(
                ToolCallRow.run_id == run.id,
                ToolCallRow.status.in_([ToolCallStatus.READY, ToolCallStatus.EXECUTING]),
            )
        )
    assert active_count == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_run_cannot_terminalize_while_active_tool_call_remains() -> None:
    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store = PostgresRuntimeStore(sessions)
    run = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="do not terminalize early",
        idempotency_key="integration-terminal-guard-1",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="worker-a", lease_seconds=30)
    assert claimed is not None
    recorder = PostgresExecutionRecorder(
        sessions, run_id=run.id, generation=claimed.execution_generation
    )
    _, invocation = await recorder.begin_model_invocation(
        run_id=run.id, invocation_id=uuid4(), expected_generation=1
    )
    invocation.complete("TOOL_PROPOSAL")
    proposal = ToolProposal.create(
        run_id=run.id,
        model_invocation_id=invocation.id,
        tool_name="echo_read",
        arguments={"text": "still active"},
    )
    agent_version = await store.load_agent_version(DEMO_AGENT_VERSION_ID)
    prepared = ToolCoordinator(build_demo_registry()).prepare_read(
        proposal=proposal, agent_version=agent_version
    )
    await recorder.record_model_tool_started(
        invocation, proposal, prepared.call, expected_generation=1
    )

    claimed.fail("synthetic terminalization attempt")
    with pytest.raises(RuntimeError, match="active ToolCall"):
        await recorder.record_run_failed(claimed, expected_generation=1)

    durable = await store.get_run(run.id)
    assert durable is not None
    assert durable.status is RunStatus.RUNNING
    await engine.dispose()


@pytest.mark.asyncio
async def test_database_rejects_two_started_model_invocations_for_one_run() -> None:
    from sqlalchemy.exc import IntegrityError

    from agentforge.infrastructure.db.models import ModelInvocationRow

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store = PostgresRuntimeStore(sessions)
    run = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="only one model request may be in flight",
        idempotency_key="integration-one-started-model-1",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="worker-a", lease_seconds=30)
    assert claimed is not None
    recorder = PostgresExecutionRecorder(
        sessions, run_id=run.id, generation=claimed.execution_generation
    )
    _, first = await recorder.begin_model_invocation(
        run_id=run.id, invocation_id=uuid4(), expected_generation=1
    )

    async with sessions() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                session.add(
                    ModelInvocationRow(
                        id=uuid4(),
                        run_id=run.id,
                        turn=first.turn + 1,
                        status="STARTED",
                        outcome_type=None,
                        error=None,
                    )
                )
                await session.flush()

    async with sessions() as session:
        started_count = await session.scalar(
            select(func.count())
            .select_from(ModelInvocationRow)
            .where(
                ModelInvocationRow.run_id == run.id,
                ModelInvocationRow.status == "STARTED",
            )
        )
    assert started_count == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_failed_run_creation_rolls_back_idempotency_record_atomically() -> None:
    from agentforge.infrastructure.db.models import IdempotencyRecordRow

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store = PostgresRuntimeStore(sessions)
    key = "integration-idempotency-rollback-1"

    with pytest.raises(KeyError):
        await store.create_run(
            agent_version_id=uuid4(),
            input_text="this create must roll back",
            idempotency_key=key,
            principal_scope="test-user",
        )

    async with sessions() as session:
        stale_record_count = await session.scalar(
            select(func.count())
            .select_from(IdempotencyRecordRow)
            .where(
                IdempotencyRecordRow.principal_scope == "test-user",
                IdempotencyRecordRow.endpoint == "POST:/v1/runs",
                IdempotencyRecordRow.idempotency_key == key,
            )
        )
    assert stale_record_count == 0

    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="this create should now succeed",
        idempotency_key=key,
        principal_scope="test-user",
    )
    assert created.status is RunStatus.QUEUED
    await engine.dispose()


@pytest.mark.asyncio
async def test_begin_model_is_rejected_while_read_tool_call_is_active() -> None:
    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store = PostgresRuntimeStore(sessions)
    run = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="cross-boundary progression guard",
        idempotency_key="integration-cross-boundary-model-1",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="worker-a", lease_seconds=30)
    assert claimed is not None
    recorder = PostgresExecutionRecorder(
        sessions, run_id=run.id, generation=claimed.execution_generation
    )
    _, invocation = await recorder.begin_model_invocation(
        run_id=run.id, invocation_id=uuid4(), expected_generation=1
    )
    invocation.complete("TOOL_PROPOSAL")
    proposal = ToolProposal.create(
        run_id=run.id,
        model_invocation_id=invocation.id,
        tool_name="echo_read",
        arguments={"text": "active"},
    )
    agent_version = await store.load_agent_version(DEMO_AGENT_VERSION_ID)
    prepared = ToolCoordinator(build_demo_registry()).prepare_read(
        proposal=proposal, agent_version=agent_version
    )
    await recorder.record_model_tool_started(
        invocation, proposal, prepared.call, expected_generation=1
    )

    with pytest.raises(RuntimeError, match="active ToolCall"):
        await recorder.begin_model_invocation(
            run_id=run.id,
            invocation_id=uuid4(),
            expected_generation=1,
        )

    await engine.dispose()


@pytest.mark.asyncio
async def test_recovered_read_start_is_rejected_while_model_invocation_is_started() -> None:
    from agentforge.infrastructure.db.models import ModelInvocationRow

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store = PostgresRuntimeStore(sessions)
    run = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="inverse cross-boundary progression guard",
        idempotency_key="integration-cross-boundary-read-1",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="worker-a", lease_seconds=30)
    assert claimed is not None
    recorder = PostgresExecutionRecorder(
        sessions, run_id=run.id, generation=claimed.execution_generation
    )
    _, invocation = await recorder.begin_model_invocation(
        run_id=run.id, invocation_id=uuid4(), expected_generation=1
    )
    invocation.complete("TOOL_PROPOSAL")
    proposal = ToolProposal.create(
        run_id=run.id,
        model_invocation_id=invocation.id,
        tool_name="echo_read",
        arguments={"text": "recover"},
    )
    agent_version = await store.load_agent_version(DEMO_AGENT_VERSION_ID)
    prepared = ToolCoordinator(build_demo_registry()).prepare_read(
        proposal=proposal, agent_version=agent_version
    )
    await recorder.record_model_tool_started(
        invocation, proposal, prepared.call, expected_generation=1
    )

    # Create the intentionally-invalid cross-aggregate state through raw DB writes:
    # the ToolCall is READY while another model request is STARTED. The recorder
    # must fail closed rather than allow both execution boundaries to be active.
    started_id = uuid4()
    async with sessions() as session, session.begin():
        call_row = await session.get(ToolCallRow, prepared.call.id)
        assert call_row is not None
        call_row.status = ToolCallStatus.READY
        session.add(
            ModelInvocationRow(
                id=started_id,
                run_id=run.id,
                turn=invocation.turn + 1,
                status="STARTED",
                outcome_type=None,
                error=None,
            )
        )

    prepared.call.retry_ready("synthetic cross-boundary state")
    prepared.call.start()
    with pytest.raises(RuntimeError, match="STARTED ModelInvocation"):
        await recorder.record_recovered_read_started(prepared.call, expected_generation=1)

    await engine.dispose()


@pytest.mark.asyncio
async def test_database_rejects_invalid_completed_run_shape() -> None:
    from sqlalchemy import update
    from sqlalchemy.exc import IntegrityError

    from agentforge.infrastructure.db.models import RunRow

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store = PostgresRuntimeStore(sessions)
    run = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="terminal row shape",
        idempotency_key="integration-terminal-shape-1",
        principal_scope="test-user",
    )

    async with sessions() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                await session.execute(
                    update(RunRow).where(RunRow.id == run.id).values(status=RunStatus.COMPLETED)
                )
                await session.flush()

    durable = await store.get_run(run.id)
    assert durable is not None
    assert durable.status is RunStatus.QUEUED
    await engine.dispose()
