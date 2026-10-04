# ruff: noqa: E402

import asyncio
import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text, update

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

from agentforge.application.errors import (
    BusinessProgressionBlockedError,
    IdempotencyConflictError,
    RunExecutionFailedError,
    SideEffectTransientError,
    StaleExecutorError,
    ToolAdapterError,
    ToolTransientError,
)
from agentforge.application.ports import ReconciliationResult
from agentforge.application.run_manager import RunManager
from agentforge.application.worker import CoreWorker
from agentforge.demo import (
    DEMO_AGENT_ID,
    DEMO_AGENT_VERSION_ID,
    DEMO_TOOL_ID,
    DEMO_TOOL_VERSION_ID,
    build_demo_model,
    build_demo_registry,
)
from agentforge.domain.enums import (
    EventType,
    QueueReason,
    ReconciliationAttemptStatus,
    ReconciliationBusinessResult,
    RunStatus,
    ToolCallStatus,
    ToolEffectType,
    ToolExecutionAttemptStatus,
)
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
    ReconciliationAttemptRow,
    RunMessageRow,
    ToolCallRow,
    ToolDefinitionRow,
    ToolExecutionAttemptRow,
    ToolProposalRow,
    ToolVersionRow,
)
from agentforge.infrastructure.db.runtime_store import PostgresRuntimeStore
from agentforge.infrastructure.db.session import create_engine, create_session_factory
from agentforge.runtime.fake_model import FinalStep, ScriptedFakeModel, ToolStep
from agentforge.runtime.native_runner import NativeRunner
from agentforge.runtime.tool_coordinator import ToolCoordinator
from agentforge.runtime.tools import FunctionTool, InMemoryToolRegistry, SideEffectFunctionTool


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
        attempts = (
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
    assert calls[0].status is ToolCallStatus.SUCCEEDED
    assert [attempt.attempt_number for attempt in attempts] == [1, 2]
    assert [attempt.execution_generation for attempt in attempts] == [1, 2]
    assert [attempt.status for attempt in attempts] == [
        ToolExecutionAttemptStatus.UNKNOWN,
        ToolExecutionAttemptStatus.SUCCEEDED,
    ]
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


@pytest.mark.asyncio
async def test_run_creation_persists_database_derived_limits_and_zero_usage() -> None:
    from agentforge.domain.models import (
        DEFAULT_MAX_MODEL_INVOCATIONS,
        DEFAULT_MAX_TOOL_ATTEMPTS,
    )

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store = PostgresRuntimeStore(sessions)

    run = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="durable limits",
        idempotency_key="integration-run-limits-1",
        principal_scope="test-user",
    )
    state = await store.load_run_state(run.id)

    assert run.max_model_invocations == DEFAULT_MAX_MODEL_INVOCATIONS
    assert run.max_tool_attempts == DEFAULT_MAX_TOOL_ATTEMPTS
    assert run.deadline_at > run.created_at
    assert state.model_invocations_used == 0
    assert state.tool_attempts_used == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_database_deadline_blocks_model_start_without_consuming_budget() -> None:
    from agentforge.infrastructure.db.models import ModelInvocationRow, RunRow

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store = PostgresRuntimeStore(sessions)
    run = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="expire before model",
        idempotency_key="integration-deadline-model-1",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="worker-a", lease_seconds=30)
    assert claimed is not None

    async with sessions() as session, session.begin():
        await session.execute(
            update(RunRow)
            .where(RunRow.id == run.id)
            .values(deadline_at=func.clock_timestamp() - text("INTERVAL '1 second'"))
        )

    recorder = PostgresExecutionRecorder(
        sessions,
        run_id=run.id,
        generation=claimed.execution_generation,
    )
    with pytest.raises(BusinessProgressionBlockedError, match="DEADLINE_EXCEEDED"):
        await recorder.begin_model_invocation(
            run_id=run.id,
            invocation_id=uuid4(),
            expected_generation=claimed.execution_generation,
        )

    state = await store.load_run_state(run.id)
    assert state.model_invocations_used == 0
    async with sessions() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(ModelInvocationRow)
            .where(ModelInvocationRow.run_id == run.id)
        )
    assert count == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_model_result_after_database_deadline_is_discarded_for_progression() -> None:
    from agentforge.domain.enums import MessageRole
    from agentforge.domain.models import RunMessage
    from agentforge.infrastructure.db.models import ModelInvocationRow, RunRow

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store = PostgresRuntimeStore(sessions)
    run = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="deadline during model",
        idempotency_key="integration-deadline-result-1",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="worker-a", lease_seconds=30)
    assert claimed is not None
    recorder = PostgresExecutionRecorder(
        sessions,
        run_id=run.id,
        generation=claimed.execution_generation,
    )
    _, invocation = await recorder.begin_model_invocation(
        run_id=run.id,
        invocation_id=uuid4(),
        expected_generation=claimed.execution_generation,
    )
    invocation.complete("FINAL")
    message = RunMessage(
        run.id,
        0,
        MessageRole.ASSISTANT,
        "late final answer",
        invocation.id,
    )

    async with sessions() as session, session.begin():
        await session.execute(
            update(RunRow)
            .where(RunRow.id == run.id)
            .values(deadline_at=func.clock_timestamp() - text("INTERVAL '1 second'"))
        )

    with pytest.raises(BusinessProgressionBlockedError) as exc_info:
        await recorder.record_model_final_decision(
            invocation,
            claimed,
            message,
            expected_generation=claimed.execution_generation,
        )

    claimed.fail(exc_info.value.failure_reason)
    await recorder.record_model_result_discarded_and_fail_run(
        invocation,
        claimed,
        exc_info.value.failure_reason,
        expected_generation=claimed.execution_generation,
    )

    durable = await store.get_run(run.id)
    assert durable is not None
    assert durable.status is RunStatus.FAILED
    assert durable.failure_reason is not None
    assert "DEADLINE_EXCEEDED" in durable.failure_reason

    async with sessions() as session:
        invocation_row = await session.get(ModelInvocationRow, invocation.id)
        assert invocation_row is not None
        assert invocation_row.status == "COMPLETED"
        assistant_messages = await session.scalar(
            select(func.count())
            .select_from(RunMessageRow)
            .where(
                RunMessageRow.run_id == run.id,
                RunMessageRow.role == MessageRole.ASSISTANT.value,
            )
        )
        discarded = await session.scalar(
            select(func.count())
            .select_from(DomainEventRow)
            .where(
                DomainEventRow.run_id == run.id,
                DomainEventRow.event_type == EventType.MODEL_RESULT_DISCARDED.value,
            )
        )
    assert assistant_messages == 0
    assert discarded == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_durable_yield_releases_lease_and_reclaims_with_new_generation() -> None:
    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store = PostgresRuntimeStore(sessions)
    run = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="cooperative yield",
        idempotency_key="integration-yield-1",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="worker-a", lease_seconds=30)
    assert claimed is not None
    assert claimed.execution_generation == 1

    recorder = PostgresExecutionRecorder(
        sessions,
        run_id=run.id,
        generation=claimed.execution_generation,
    )
    claimed.yield_to_queue(QueueReason.YIELD)
    await recorder.record_run_yielded(
        claimed,
        delay_seconds=0,
        expected_generation=1,
    )

    queued = await store.get_run(run.id)
    assert queued is not None
    assert queued.status is RunStatus.QUEUED
    assert queued.queue_reason is QueueReason.YIELD
    assert queued.owner_worker_id is None
    assert queued.lease_expires_at is None
    assert queued.available_at is not None

    reclaimed = await store.claim_next_run(worker_id="worker-b", lease_seconds=30)
    assert reclaimed is not None
    assert reclaimed.id == run.id
    assert reclaimed.execution_generation == 2
    assert reclaimed.available_at is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_model_and_tool_start_reserve_usage_atomically() -> None:
    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store = PostgresRuntimeStore(sessions)
    run = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="reserve usage",
        idempotency_key="integration-usage-reservation-1",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="worker-a", lease_seconds=30)
    assert claimed is not None
    recorder = PostgresExecutionRecorder(
        sessions,
        run_id=run.id,
        generation=claimed.execution_generation,
    )
    _, invocation = await recorder.begin_model_invocation(
        run_id=run.id,
        invocation_id=uuid4(),
        expected_generation=1,
    )
    state = await store.load_run_state(run.id)
    assert state.model_invocations_used == 1
    assert state.tool_attempts_used == 0

    invocation.complete("TOOL_PROPOSAL")
    proposal = ToolProposal.create(
        run_id=run.id,
        model_invocation_id=invocation.id,
        tool_name="echo_read",
        arguments={"text": "reserve"},
    )
    agent_version = await store.load_agent_version(DEMO_AGENT_VERSION_ID)
    prepared = ToolCoordinator(build_demo_registry()).prepare_read(
        proposal=proposal,
        agent_version=agent_version,
    )
    await recorder.record_model_tool_started(
        invocation,
        proposal,
        prepared.call,
        expected_generation=1,
    )

    state = await store.load_run_state(run.id)
    assert state.model_invocations_used == 1
    assert state.tool_attempts_used == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_stale_executor_precedes_deadline_for_model_result() -> None:
    from agentforge.domain.enums import MessageRole
    from agentforge.domain.models import RunMessage
    from agentforge.infrastructure.db.models import ModelInvocationRow, RunRow

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store = PostgresRuntimeStore(sessions)
    run = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="stale wins over deadline",
        idempotency_key="integration-stale-deadline-1",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="worker-a", lease_seconds=1)
    assert claimed is not None
    recorder = PostgresExecutionRecorder(
        sessions,
        run_id=run.id,
        generation=claimed.execution_generation,
    )
    _, invocation = await recorder.begin_model_invocation(
        run_id=run.id,
        invocation_id=uuid4(),
        expected_generation=claimed.execution_generation,
    )
    invocation.complete("FINAL")
    message = RunMessage(
        run.id,
        0,
        MessageRole.ASSISTANT,
        "late stale answer",
        invocation.id,
    )

    await asyncio.sleep(1.2)
    async with sessions() as session, session.begin():
        await session.execute(
            update(RunRow)
            .where(RunRow.id == run.id)
            .values(deadline_at=func.clock_timestamp() - text("INTERVAL '1 second'"))
        )

    with pytest.raises(StaleExecutorError):
        await recorder.record_model_final_decision(
            invocation,
            claimed,
            message,
            expected_generation=claimed.execution_generation,
        )

    async with sessions() as session:
        invocation_row = await session.get(ModelInvocationRow, invocation.id)
        assert invocation_row is not None
        assert invocation_row.status == "STARTED"
        discarded = await session.scalar(
            select(func.count())
            .select_from(DomainEventRow)
            .where(
                DomainEventRow.run_id == run.id,
                DomainEventRow.event_type == EventType.MODEL_RESULT_DISCARDED.value,
            )
        )
    assert discarded == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_expired_deadline_blocks_recovered_read_without_new_attempt_or_usage() -> None:
    from agentforge.infrastructure.db.models import RunRow

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store = PostgresRuntimeStore(sessions)
    run = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="blocked recovered read",
        idempotency_key="integration-recovered-deadline-1",
        principal_scope="test-user",
    )
    claimed_a = await store.claim_next_run(worker_id="worker-a", lease_seconds=1)
    assert claimed_a is not None
    recorder_a = PostgresExecutionRecorder(
        sessions,
        run_id=run.id,
        generation=claimed_a.execution_generation,
    )
    _, invocation = await recorder_a.begin_model_invocation(
        run_id=run.id,
        invocation_id=uuid4(),
        expected_generation=1,
    )
    invocation.complete("TOOL_PROPOSAL")
    proposal = ToolProposal.create(
        run_id=run.id,
        model_invocation_id=invocation.id,
        tool_name="echo_read",
        arguments={"text": "retry must be blocked"},
    )
    agent_version = await store.load_agent_version(DEMO_AGENT_VERSION_ID)
    prepared = ToolCoordinator(build_demo_registry()).prepare_read(
        proposal=proposal,
        agent_version=agent_version,
    )
    await recorder_a.record_model_tool_started(
        invocation,
        proposal,
        prepared.call,
        expected_generation=1,
    )

    before = await store.load_run_state(run.id)
    assert before.tool_attempts_used == 1
    await asyncio.sleep(1.2)
    claimed_b = await store.claim_next_run(worker_id="worker-b", lease_seconds=30)
    assert claimed_b is not None
    assert claimed_b.execution_generation == 2

    async with sessions() as session, session.begin():
        await session.execute(
            update(RunRow)
            .where(RunRow.id == run.id)
            .values(deadline_at=func.clock_timestamp() - text("INTERVAL '1 second'"))
        )

    recorder_b = PostgresExecutionRecorder(
        sessions,
        run_id=run.id,
        generation=claimed_b.execution_generation,
    )
    recovered = await recorder_b.load_recoverable_read_call(run.id)
    assert recovered is not None
    recovered = (
        ToolCoordinator(build_demo_registry())
        .prepare_recovered_read(
            call=recovered,
            agent_version=agent_version,
        )
        .call
    )

    with pytest.raises(BusinessProgressionBlockedError, match="DEADLINE_EXCEEDED"):
        await recorder_b.record_recovered_read_started(
            recovered,
            expected_generation=2,
        )

    after = await store.load_run_state(run.id)
    assert after.tool_attempts_used == 1
    async with sessions() as session:
        attempts = (
            (
                await session.execute(
                    select(ToolExecutionAttemptRow)
                    .where(ToolExecutionAttemptRow.run_id == run.id)
                    .order_by(ToolExecutionAttemptRow.attempt_number)
                )
            )
            .scalars()
            .all()
        )
    assert len(attempts) == 1
    assert attempts[0].status is ToolExecutionAttemptStatus.UNKNOWN

    await engine.dispose()


@pytest.mark.asyncio
async def test_read_transient_retry_uses_db_time_and_survives_worker_restart() -> None:
    from agentforge.infrastructure.db.models import ToolExecutionAttemptRow

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)

    async with sessions() as session, session.begin():
        tool_version = await session.get(ToolVersionRow, DEMO_TOOL_VERSION_ID)
        assert tool_version is not None
        tool_version.read_retry_max_attempts = 3
        tool_version.read_retry_initial_backoff_seconds = 1
        tool_version.read_retry_max_backoff_seconds = 4

    invocations = 0

    async def flaky_echo(text: str):
        nonlocal invocations
        invocations += 1
        if invocations == 1:
            raise ToolTransientError("temporary read outage")
        return {"echo": text}

    registry = InMemoryToolRegistry(
        [
            FunctionTool(
                version_id=DEMO_TOOL_VERSION_ID,
                name="echo_read",
                description="retryable read",
                input_schema={"type": "object"},
                func=flaky_echo,
            )
        ]
    )
    store = PostgresRuntimeStore(sessions)
    run = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="durable read retry",
        idempotency_key="integration-read-transient-retry-1",
        principal_scope="test-user",
    )

    worker_a = CoreWorker(
        runtime_store=store,
        recorder_factory=PostgresExecutionRecorderFactory(sessions),
        tool_registry=registry,
        model_factory=lambda _: ScriptedFakeModel(
            [ToolStep("echo_read", {"text": "durable read retry"})]
        ),
        worker_id="worker-a",
        lease_seconds=30,
    )
    assert await worker_a.run_once() is True

    scheduled = await store.get_run(run.id)
    assert scheduled is not None
    assert scheduled.status is RunStatus.QUEUED
    assert scheduled.queue_reason is QueueReason.RETRY
    assert scheduled.available_at is not None

    async with sessions() as session:
        calls = (
            (await session.execute(select(ToolCallRow).where(ToolCallRow.run_id == run.id)))
            .scalars()
            .all()
        )
        attempts = (
            (
                await session.execute(
                    select(ToolExecutionAttemptRow)
                    .where(ToolExecutionAttemptRow.run_id == run.id)
                    .order_by(ToolExecutionAttemptRow.attempt_number)
                )
            )
            .scalars()
            .all()
        )
    assert len(calls) == 1
    original_call_id = calls[0].id
    assert calls[0].status is ToolCallStatus.READY
    assert len(attempts) == 1
    assert attempts[0].status is ToolExecutionAttemptStatus.FAILED
    assert attempts[0].error_class == "TRANSIENT"
    assert attempts[0].definite_not_executed is True

    # The DB available_at gate, not lease expiry, blocks an early claim.
    assert await store.claim_next_run(worker_id="too-early", lease_seconds=30) is None

    await engine.dispose()
    await asyncio.sleep(1.2)

    restarted_engine = create_engine(DATABASE_URL)
    restarted_sessions = create_session_factory(restarted_engine)
    restarted_store = PostgresRuntimeStore(restarted_sessions)
    worker_b = CoreWorker(
        runtime_store=restarted_store,
        recorder_factory=PostgresExecutionRecorderFactory(restarted_sessions),
        tool_registry=registry,
        model_factory=lambda _: ScriptedFakeModel([FinalStep("done after retry")]),
        worker_id="worker-b",
        lease_seconds=30,
    )
    assert await worker_b.run_once() is True

    completed = await restarted_store.get_run(run.id)
    assert completed is not None
    assert completed.status is RunStatus.COMPLETED
    assert completed.execution_generation == 2

    async with restarted_sessions() as session:
        calls = (
            (await session.execute(select(ToolCallRow).where(ToolCallRow.run_id == run.id)))
            .scalars()
            .all()
        )
        attempts = (
            (
                await session.execute(
                    select(ToolExecutionAttemptRow)
                    .where(ToolExecutionAttemptRow.run_id == run.id)
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
    assert calls[0].status is ToolCallStatus.SUCCEEDED
    assert [attempt.attempt_number for attempt in attempts] == [1, 2]
    assert [attempt.status for attempt in attempts] == [
        ToolExecutionAttemptStatus.FAILED,
        ToolExecutionAttemptStatus.SUCCEEDED,
    ]
    assert EventType.TOOL_RETRY_SCHEDULED.value in event_types
    assert invocations == 2
    await restarted_engine.dispose()


@pytest.mark.asyncio
async def test_side_effect_preparation_commits_intent_without_attempt_or_external_io() -> None:
    from agentforge.domain.enums import (
        ExternalActionStatus,
        ReconciliationMode,
        ToolEffectType,
    )
    from agentforge.infrastructure.db.models import (
        ActionSnapshotRow,
        ExternalActionRow,
        RunStateRow,
        ToolExecutionAttemptRow,
    )

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)

    side_tool_id = uuid4()
    side_version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            ToolDefinitionRow(
                id=side_tool_id,
                name="create_ticket",
                description="external side effect",
            )
        )
        await session.flush()
        session.add(
            ToolVersionRow(
                id=side_version_id,
                tool_id=side_tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.EXTERNAL_SIDE_EFFECT,
                implementation_ref="tests:create_ticket",
                allow_no_approval_execution=True,
                credential_ref="credential://jira/integration",
                idempotency_supported=True,
                reconciliation_mode=ReconciliationMode.AUTHORITATIVE,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=DEMO_AGENT_VERSION_ID,
                tool_version_id=side_version_id,
                tool_alias="create_ticket",
            )
        )

    physical_calls = 0

    def forbidden_external_call(summary: str):
        nonlocal physical_calls
        physical_calls += 1
        return {"created": summary}

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
                name="create_ticket",
                description="external side effect",
                input_schema={"type": "object"},
                func=lambda invocation: forbidden_external_call(
                    str(invocation.arguments["summary"])
                ),
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="prepare side effect",
        idempotency_key="integration-side-effect-preparation-1",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="worker-side-effect-b2", lease_seconds=30)
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
        tool_name="create_ticket",
        arguments={"summary": "durable intent"},
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
    assert physical_calls == 0

    refreshed = await store.get_run(created.id)
    assert refreshed is not None
    assert refreshed.status is RunStatus.RUNNING

    async with sessions() as session:
        calls = (
            (await session.execute(select(ToolCallRow).where(ToolCallRow.run_id == created.id)))
            .scalars()
            .all()
        )
        actions = (
            (
                await session.execute(
                    select(ExternalActionRow).where(ExternalActionRow.run_id == created.id)
                )
            )
            .scalars()
            .all()
        )
        attempts = (
            (
                await session.execute(
                    select(ToolExecutionAttemptRow).where(
                        ToolExecutionAttemptRow.run_id == created.id
                    )
                )
            )
            .scalars()
            .all()
        )
        state = await session.get(RunStateRow, created.id)
        assert state is not None
        assert len(calls) == 1
        assert calls[0].status is ToolCallStatus.READY
        assert len(actions) == 1
        assert actions[0].status is ExternalActionStatus.READY
        assert actions[0].current_attempt_id is None
        snapshot = await session.get(ActionSnapshotRow, actions[0].action_snapshot_id)
        assert snapshot is not None
        assert snapshot.operation_id == actions[0].operation_id
        assert snapshot.effect_type is ToolEffectType.EXTERNAL_SIDE_EFFECT
        assert snapshot.credential_ref == "credential://jira/integration"
        assert attempts == []
        assert state.tool_attempts_used == 0

    recorder = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=refreshed.execution_generation,
    )
    assert await recorder.load_recoverable_read_call(created.id) is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_side_effect_preparation_stale_lease_creates_no_intent() -> None:
    from datetime import UTC, datetime, timedelta

    from agentforge.domain.enums import ReconciliationMode, ToolEffectType
    from agentforge.infrastructure.db.models import ActionSnapshotRow, ExternalActionRow, RunRow

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)

    side_tool_id = uuid4()
    side_version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(ToolDefinitionRow(id=side_tool_id, name="write_stale", description="write"))
        await session.flush()
        session.add(
            ToolVersionRow(
                id=side_version_id,
                tool_id=side_tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.WRITE,
                implementation_ref="tests:write_stale",
                allow_no_approval_execution=True,
                idempotency_supported=False,
                reconciliation_mode=ReconciliationMode.NONE,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=DEMO_AGENT_VERSION_ID,
                tool_version_id=side_version_id,
                tool_alias="write_stale",
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
                name="write_stale",
                description="write",
                input_schema={"type": "object"},
                func=lambda invocation: {"must": "not run"},
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="stale prep",
        idempotency_key="integration-side-effect-preparation-stale",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="stale-b2", lease_seconds=30)
    assert claimed is not None
    recorder = PostgresExecutionRecorder(
        sessions,
        run_id=claimed.id,
        generation=claimed.execution_generation,
    )
    _, invocation = await recorder.begin_model_invocation(
        run_id=claimed.id,
        invocation_id=uuid4(),
        expected_generation=claimed.execution_generation,
    )
    proposal = ToolProposal.create(
        run_id=claimed.id,
        model_invocation_id=invocation.id,
        tool_name="write_stale",
        arguments={},
    )
    prepared = ToolCoordinator(registry).prepare_side_effect(
        proposal=proposal,
        agent_version=await store.load_agent_version(claimed.agent_version_id),
    )
    invocation.complete("TOOL_PROPOSAL")

    async with sessions() as session, session.begin():
        row = await session.get(RunRow, claimed.id)
        assert row is not None
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)

    with pytest.raises(StaleExecutorError):
        await recorder.record_model_side_effect_prepared(
            invocation,
            proposal,
            prepared.call,
            prepared.snapshot,
            prepared.action,
            expected_generation=claimed.execution_generation,
        )

    async with sessions() as session:
        action_count = await session.scalar(select(func.count()).select_from(ExternalActionRow))
        snapshot_count = await session.scalar(select(func.count()).select_from(ActionSnapshotRow))
        call_count = await session.scalar(
            select(func.count()).select_from(ToolCallRow).where(ToolCallRow.run_id == claimed.id)
        )
    assert action_count == 0
    assert snapshot_count == 0
    assert call_count == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_side_effect_preparation_rechecks_durable_toolversion_eligibility() -> None:
    from agentforge.domain.enums import ReconciliationMode, ToolEffectType
    from agentforge.infrastructure.db.models import ActionSnapshotRow, ExternalActionRow

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)

    side_tool_id = uuid4()
    side_version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(ToolDefinitionRow(id=side_tool_id, name="write_policy", description="write"))
        await session.flush()
        session.add(
            ToolVersionRow(
                id=side_version_id,
                tool_id=side_tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.WRITE,
                implementation_ref="tests:write_policy",
                allow_no_approval_execution=True,
                reconciliation_mode=ReconciliationMode.NONE,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=DEMO_AGENT_VERSION_ID,
                tool_version_id=side_version_id,
                tool_alias="write_policy",
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
                name="write_policy",
                description="write",
                input_schema={"type": "object"},
                func=lambda invocation: {"must": "not run"},
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="policy prep",
        idempotency_key="integration-side-effect-preparation-policy",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="policy-b2", lease_seconds=30)
    assert claimed is not None
    agent_version = await store.load_agent_version(claimed.agent_version_id)
    recorder = PostgresExecutionRecorder(
        sessions,
        run_id=claimed.id,
        generation=claimed.execution_generation,
    )
    _, invocation = await recorder.begin_model_invocation(
        run_id=claimed.id,
        invocation_id=uuid4(),
        expected_generation=claimed.execution_generation,
    )
    proposal = ToolProposal.create(
        run_id=claimed.id,
        model_invocation_id=invocation.id,
        tool_name="write_policy",
        arguments={},
    )
    prepared = ToolCoordinator(registry).prepare_side_effect(
        proposal=proposal,
        agent_version=agent_version,
    )
    invocation.complete("TOOL_PROPOSAL")

    async with sessions() as session, session.begin():
        durable_version = await session.get(ToolVersionRow, side_version_id)
        assert durable_version is not None
        durable_version.allow_no_approval_execution = False

    with pytest.raises(PermissionError):
        await recorder.record_model_side_effect_prepared(
            invocation,
            proposal,
            prepared.call,
            prepared.snapshot,
            prepared.action,
            expected_generation=claimed.execution_generation,
        )

    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(ExternalActionRow)) == 0
        assert await session.scalar(select(func.count()).select_from(ActionSnapshotRow)) == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_action_commit_is_visible_before_physical_side_effect() -> None:
    from agentforge.application.ports import SideEffectInvocation
    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode
    from agentforge.infrastructure.db.models import (
        ActionSnapshotRow,
        ExternalActionRow,
        RunStateRow,
    )

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)

    side_tool_id = uuid4()
    side_version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            ToolDefinitionRow(id=side_tool_id, name="create_commit_ticket", description="write")
        )
        await session.flush()
        session.add(
            ToolVersionRow(
                id=side_version_id,
                tool_id=side_tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.EXTERNAL_SIDE_EFFECT,
                implementation_ref="tests:create_commit_ticket",
                allow_no_approval_execution=True,
                credential_ref="credential://jira/c1-integration",
                idempotency_supported=True,
                reconciliation_mode=ReconciliationMode.AUTHORITATIVE,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=DEMO_AGENT_VERSION_ID,
                tool_version_id=side_version_id,
                tool_alias="create_commit_ticket",
            )
        )

    physical_calls = 0

    async def external_effect(invocation: SideEffectInvocation):
        nonlocal physical_calls
        # A fresh transaction must see the full authorization tuple before effect.
        async with sessions() as observer:
            action = (
                await observer.execute(
                    select(ExternalActionRow).where(
                        ExternalActionRow.operation_id == invocation.operation_id
                    )
                )
            ).scalar_one()
            call = await observer.get(ToolCallRow, action.tool_call_id)
            snapshot = await observer.get(ActionSnapshotRow, action.action_snapshot_id)
            attempt = await observer.get(ToolExecutionAttemptRow, action.current_attempt_id)
            state = await observer.get(RunStateRow, action.run_id)
            assert call is not None and call.status is ToolCallStatus.EXECUTING
            assert snapshot is not None and snapshot.digest
            assert snapshot.operation_id == invocation.operation_id
            assert action.status is ExternalActionStatus.EXECUTING
            assert action.current_attempt_id is not None
            assert attempt is not None
            assert attempt.status is ToolExecutionAttemptStatus.STARTED
            assert attempt.external_action_id == action.id
            assert state is not None and state.tool_attempts_used == 1
        physical_calls += 1
        return {"ticket_id": "T-C1", "operation_id": str(invocation.operation_id)}

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
                name="create_commit_ticket",
                description="write",
                input_schema={"type": "object"},
                func=external_effect,
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="commit before effect",
        idempotency_key="integration-action-commit-visible-1",
        principal_scope="test-user",
    )
    worker = CoreWorker(
        runtime_store=store,
        recorder_factory=PostgresExecutionRecorderFactory(sessions),
        tool_registry=registry,
        model_factory=lambda _: ScriptedFakeModel(
            [
                ToolStep("create_commit_ticket", {"summary": "commit first"}),
                FinalStep("ticket created"),
            ]
        ),
        worker_id="worker-action-commit",
        lease_seconds=30,
    )

    assert await worker.run_once() is True
    assert physical_calls == 1

    durable = await store.get_run(created.id)
    assert durable is not None and durable.status is RunStatus.COMPLETED
    state = await store.load_run_state(created.id)
    assert state.tool_attempts_used == 1

    async with sessions() as session:
        action = (
            (
                await session.execute(
                    select(ExternalActionRow).where(ExternalActionRow.run_id == created.id)
                )
            )
            .scalars()
            .one()
        )
        call = await session.get(ToolCallRow, action.tool_call_id)
        attempt = (
            (
                await session.execute(
                    select(ToolExecutionAttemptRow).where(
                        ToolExecutionAttemptRow.external_action_id == action.id
                    )
                )
            )
            .scalars()
            .one()
        )
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
    assert action.status is ExternalActionStatus.SUCCEEDED
    assert action.current_attempt_id is None
    assert call is not None and call.status is ToolCallStatus.SUCCEEDED
    assert attempt.status is ToolExecutionAttemptStatus.SUCCEEDED
    assert EventType.ACTION_PREPARED.value in event_types
    assert EventType.ACTION_COMMITTED.value in event_types
    assert EventType.ACTION_SUCCEEDED.value in event_types
    await engine.dispose()


@pytest.mark.asyncio
async def test_ready_action_recovery_uses_same_operation_id_without_model_reproposal() -> None:
    from agentforge.application.ports import SideEffectInvocation
    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode
    from agentforge.infrastructure.db.models import ExternalActionRow

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)

    side_tool_id = uuid4()
    side_version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(ToolDefinitionRow(id=side_tool_id, name="recover_write", description="write"))
        await session.flush()
        session.add(
            ToolVersionRow(
                id=side_version_id,
                tool_id=side_tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.WRITE,
                implementation_ref="tests:recover_write",
                allow_no_approval_execution=True,
                idempotency_supported=True,
                reconciliation_mode=ReconciliationMode.NONE,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=DEMO_AGENT_VERSION_ID,
                tool_version_id=side_version_id,
                tool_alias="recover_write",
            )
        )

    observed_operation_ids = []

    async def external_effect(invocation: SideEffectInvocation):
        observed_operation_ids.append(invocation.operation_id)
        return {"resource_id": "R-RECOVERED"}

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
                name="recover_write",
                description="write",
                input_schema={"type": "object"},
                func=external_effect,
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="recover ready action",
        idempotency_key="integration-ready-action-recovery-1",
        principal_scope="test-user",
    )
    claimed_a = await store.claim_next_run(worker_id="worker-ready-a", lease_seconds=1)
    assert claimed_a is not None
    recorder_a = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed_a.execution_generation,
    )
    _, invocation = await recorder_a.begin_model_invocation(
        run_id=created.id,
        invocation_id=uuid4(),
        expected_generation=claimed_a.execution_generation,
    )
    invocation.complete("TOOL_PROPOSAL")
    proposal = ToolProposal.create(
        run_id=created.id,
        model_invocation_id=invocation.id,
        tool_name="recover_write",
        arguments={"value": "same intent"},
    )
    prepared = ToolCoordinator(registry).prepare_side_effect(
        proposal=proposal,
        agent_version=await store.load_agent_version(DEMO_AGENT_VERSION_ID),
    )
    await recorder_a.record_model_side_effect_prepared(
        invocation,
        proposal,
        prepared.call,
        prepared.snapshot,
        prepared.action,
        expected_generation=claimed_a.execution_generation,
    )
    original_operation_id = prepared.action.operation_id

    await asyncio.sleep(1.2)
    worker_b = CoreWorker(
        runtime_store=store,
        recorder_factory=PostgresExecutionRecorderFactory(sessions),
        tool_registry=registry,
        model_factory=lambda _: ScriptedFakeModel([FinalStep("recovered and complete")]),
        worker_id="worker-ready-b",
        lease_seconds=30,
    )
    assert await worker_b.run_once() is True

    assert observed_operation_ids == [original_operation_id]
    durable = await store.get_run(created.id)
    assert durable is not None and durable.status is RunStatus.COMPLETED
    assert durable.execution_generation == 2
    async with sessions() as session:
        action = (
            (
                await session.execute(
                    select(ExternalActionRow).where(ExternalActionRow.run_id == created.id)
                )
            )
            .scalars()
            .one()
        )
        proposals = await session.scalar(
            select(func.count())
            .select_from(ToolProposalRow)
            .where(ToolProposalRow.run_id == created.id)
        )
    assert action.operation_id == original_operation_id
    assert action.status is ExternalActionStatus.SUCCEEDED
    assert proposals == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_action_commit_deadline_block_aborts_ready_action_without_external_call() -> None:
    from agentforge.application.ports import SideEffectInvocation
    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode
    from agentforge.infrastructure.db.models import ExternalActionRow, RunRow

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)

    side_tool_id = uuid4()
    side_version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(ToolDefinitionRow(id=side_tool_id, name="deadline_write", description="write"))
        await session.flush()
        session.add(
            ToolVersionRow(
                id=side_version_id,
                tool_id=side_tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.WRITE,
                implementation_ref="tests:deadline_write",
                allow_no_approval_execution=True,
                idempotency_supported=False,
                reconciliation_mode=ReconciliationMode.NONE,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=DEMO_AGENT_VERSION_ID,
                tool_version_id=side_version_id,
                tool_alias="deadline_write",
            )
        )

    calls = 0

    async def forbidden(invocation: SideEffectInvocation):
        nonlocal calls
        calls += 1
        return {"unexpected": True}

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
                name="deadline_write",
                description="write",
                input_schema={"type": "object"},
                func=forbidden,
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="deadline after ready",
        idempotency_key="integration-action-commit-deadline-1",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="worker-deadline-a", lease_seconds=30)
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
        tool_name="deadline_write",
        arguments={},
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
    async with sessions() as session, session.begin():
        await session.execute(
            update(RunRow)
            .where(RunRow.id == created.id)
            .values(deadline_at=func.clock_timestamp() - text("INTERVAL '1 second'"))
        )

    manager = RunManager(
        NativeRunner(ScriptedFakeModel([FinalStep("must not reason")]), registry),
        ToolCoordinator(registry),
    )
    with pytest.raises(RunExecutionFailedError, match="DEADLINE_EXCEEDED"):
        await manager.execute(
            run=claimed,
            run_state=await store.load_run_state(created.id),
            agent_version=await store.load_agent_version(DEMO_AGENT_VERSION_ID),
            recorder=recorder,
        )

    assert calls == 0
    durable = await store.get_run(created.id)
    assert durable is not None and durable.status is RunStatus.FAILED
    state = await store.load_run_state(created.id)
    assert state.tool_attempts_used == 0
    async with sessions() as session:
        action = (
            (
                await session.execute(
                    select(ExternalActionRow).where(ExternalActionRow.run_id == created.id)
                )
            )
            .scalars()
            .one()
        )
        call = await session.get(ToolCallRow, action.tool_call_id)
        attempts = await session.scalar(
            select(func.count())
            .select_from(ToolExecutionAttemptRow)
            .where(ToolExecutionAttemptRow.run_id == created.id)
        )
    assert action.status is ExternalActionStatus.ABORTED
    assert action.current_attempt_id is None
    assert call is not None and call.status is ToolCallStatus.NOT_EXECUTED
    assert attempts == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_side_effect_ambiguous_result_persists_unknown_without_new_reasoning() -> None:
    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode
    from agentforge.infrastructure.db.models import (
        ExternalActionRow,
        ModelInvocationRow,
    )

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)

    side_tool_id = uuid4()
    side_version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            ToolDefinitionRow(id=side_tool_id, name="ambiguous_ticket", description="write")
        )
        await session.flush()
        session.add(
            ToolVersionRow(
                id=side_version_id,
                tool_id=side_tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.EXTERNAL_SIDE_EFFECT,
                implementation_ref="tests:ambiguous_ticket",
                allow_no_approval_execution=True,
                idempotency_supported=False,
                reconciliation_mode=ReconciliationMode.AUTHORITATIVE,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=DEMO_AGENT_VERSION_ID,
                tool_version_id=side_version_id,
                tool_alias="ambiguous_ticket",
            )
        )

    physical_calls = 0

    async def ambiguous(_invocation):
        nonlocal physical_calls
        physical_calls += 1
        raise ToolAdapterError(
            "response lost after request may have committed",
            error_class="RESPONSE_LOST",
            definite_not_executed=False,
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
                name="ambiguous_ticket",
                description="write",
                input_schema={"type": "object"},
                func=ambiguous,
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="ambiguous side effect",
        idempotency_key="integration-d1-ambiguous-1",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="worker-d1", lease_seconds=30)
    assert claimed is not None
    recorder = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed.execution_generation,
    )
    manager = RunManager(
        NativeRunner(
            ScriptedFakeModel(
                [
                    ToolStep("ambiguous_ticket", {"summary": "maybe created"}),
                    FinalStep("must not be reached"),
                ]
            ),
            registry,
        ),
        ToolCoordinator(registry),
    )

    result = await manager.execute(
        run=claimed,
        run_state=await store.load_run_state(created.id),
        agent_version=await store.load_agent_version(DEMO_AGENT_VERSION_ID),
        recorder=recorder,
    )
    assert result is None
    assert physical_calls == 1

    async with sessions() as session:
        action = (
            await session.execute(
                select(ExternalActionRow).where(ExternalActionRow.run_id == created.id)
            )
        ).scalar_one()
        call = await session.get(ToolCallRow, action.tool_call_id)
        attempt = (
            await session.execute(
                select(ToolExecutionAttemptRow).where(
                    ToolExecutionAttemptRow.external_action_id == action.id
                )
            )
        ).scalar_one()
        invocations = await session.scalar(
            select(func.count())
            .select_from(ModelInvocationRow)
            .where(ModelInvocationRow.run_id == created.id)
        )
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
    assert attempt.status is ToolExecutionAttemptStatus.UNKNOWN
    assert attempt.definite_not_executed is False
    assert attempt.error_class == "RESPONSE_LOST"
    assert attempt.outcome_reason == "SIDE_EFFECT_POSSIBLE_EXECUTION"
    assert invocations == 1
    assert EventType.ACTION_UNKNOWN.value in event_types

    # Same generation: durable UNKNOWN short-circuits before a second model call.
    second = await manager.execute(
        run=claimed,
        run_state=await store.load_run_state(created.id),
        agent_version=await store.load_agent_version(DEMO_AGENT_VERSION_ID),
        recorder=recorder,
    )
    assert second is None
    assert physical_calls == 1
    async with sessions() as session:
        invocations_after = await session.scalar(
            select(func.count())
            .select_from(ModelInvocationRow)
            .where(ModelInvocationRow.run_id == created.id)
        )
    assert invocations_after == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_side_effect_definite_nonexecution_persists_failed_truth() -> None:
    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode
    from agentforge.infrastructure.db.models import ExternalActionRow

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)

    side_tool_id = uuid4()
    side_version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            ToolDefinitionRow(id=side_tool_id, name="preflight_failure", description="write")
        )
        await session.flush()
        session.add(
            ToolVersionRow(
                id=side_version_id,
                tool_id=side_tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.WRITE,
                implementation_ref="tests:preflight_failure",
                allow_no_approval_execution=True,
                reconciliation_mode=ReconciliationMode.NONE,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=DEMO_AGENT_VERSION_ID,
                tool_version_id=side_version_id,
                tool_alias="preflight_failure",
            )
        )

    async def definite(_invocation):
        raise ToolAdapterError(
            "credential resolution failed before external request",
            error_class="CREDENTIAL",
            definite_not_executed=True,
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
                name="preflight_failure",
                description="write",
                input_schema={"type": "object"},
                func=definite,
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="definite nonexecution",
        idempotency_key="integration-d1-definite-1",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="worker-d1-definite", lease_seconds=30)
    assert claimed is not None
    manager = RunManager(
        NativeRunner(
            ScriptedFakeModel([ToolStep("preflight_failure", {})]),
            registry,
        ),
        ToolCoordinator(registry),
    )
    recorder = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed.execution_generation,
    )

    with pytest.raises(RunExecutionFailedError, match="definitely did not execute"):
        await manager.execute(
            run=claimed,
            run_state=await store.load_run_state(created.id),
            agent_version=await store.load_agent_version(DEMO_AGENT_VERSION_ID),
            recorder=recorder,
        )

    durable = await store.get_run(created.id)
    assert durable is not None and durable.status is RunStatus.FAILED
    async with sessions() as session:
        action = (
            await session.execute(
                select(ExternalActionRow).where(ExternalActionRow.run_id == created.id)
            )
        ).scalar_one()
        call = await session.get(ToolCallRow, action.tool_call_id)
        attempt = (
            await session.execute(
                select(ToolExecutionAttemptRow).where(
                    ToolExecutionAttemptRow.external_action_id == action.id
                )
            )
        ).scalar_one()
    assert action.status is ExternalActionStatus.FAILED
    assert action.current_attempt_id is None
    assert call is not None and call.status is ToolCallStatus.FAILED
    assert attempt.status is ToolExecutionAttemptStatus.FAILED
    assert attempt.definite_not_executed is True
    assert attempt.error_class == "CREDENTIAL"
    assert attempt.outcome_reason == "SIDE_EFFECT_DEFINITE_NOT_EXECUTED"
    await engine.dispose()


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


@pytest.mark.asyncio
async def test_reconciliation_started_is_durable_before_query_and_can_finalize_success() -> None:
    from agentforge.domain.enums import ExternalActionStatus, ReconciliationMode
    from agentforge.infrastructure.db.models import ExternalActionRow

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)

    side_tool_id = uuid4()
    side_version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            ToolDefinitionRow(
                id=side_tool_id,
                name="reconcile_commit",
                description="write",
            )
        )
        await session.flush()
        session.add(
            ToolVersionRow(
                id=side_version_id,
                tool_id=side_tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.WRITE,
                implementation_ref="tests:reconcile_commit",
                allow_no_approval_execution=True,
                reconciliation_mode=ReconciliationMode.AUTHORITATIVE,
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
                tool_alias="reconcile_commit",
            )
        )

    async def ambiguous(_invocation):
        raise ToolAdapterError(
            "effect may have committed",
            error_class="RESPONSE_LOST",
            definite_not_executed=False,
        )

    observed_started_before_query = False

    async def reconcile(_invocation):
        nonlocal observed_started_before_query
        async with sessions() as session:
            attempt = (
                await session.execute(
                    select(ReconciliationAttemptRow).where(
                        ReconciliationAttemptRow.status == ReconciliationAttemptStatus.STARTED
                    )
                )
            ).scalar_one()
            action = await session.get(ExternalActionRow, attempt.external_action_id)
            observed_started_before_query = (
                action is not None and action.status is ExternalActionStatus.RECONCILING
            )
        return ReconciliationResult(
            ReconciliationBusinessResult.SUCCEEDED,
            {"resource_id": "R-committed"},
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
                name="reconcile_commit",
                description="write",
                input_schema={"type": "object"},
                func=ambiguous,
                reconcile_func=reconcile,
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="reconcile commit boundary",
        idempotency_key="integration-d3-started-before-query",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="d3-start", lease_seconds=30)
    assert claimed is not None
    version = await store.load_agent_version(DEMO_AGENT_VERSION_ID)
    manager1 = RunManager(
        NativeRunner(ScriptedFakeModel([ToolStep("reconcile_commit", {"v": 1})]), registry),
        ToolCoordinator(registry),
    )
    recorder = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed.execution_generation,
    )
    await manager1.execute(
        run=claimed,
        run_state=await store.load_run_state(created.id),
        agent_version=version,
        recorder=recorder,
    )

    manager2 = RunManager(
        NativeRunner(ScriptedFakeModel([FinalStep("reconciled")]), registry),
        ToolCoordinator(registry),
    )
    assert (
        await manager2.execute(
            run=claimed,
            run_state=await store.load_run_state(created.id),
            agent_version=version,
            recorder=recorder,
        )
        == "reconciled"
    )
    assert observed_started_before_query is True

    async with sessions() as session:
        attempt = (await session.execute(select(ReconciliationAttemptRow))).scalar_one()
        action = (await session.execute(select(ExternalActionRow))).scalar_one()
        call = await session.get(ToolCallRow, action.tool_call_id)
    assert attempt.status is ReconciliationAttemptStatus.SUCCEEDED
    assert attempt.business_result is ReconciliationBusinessResult.SUCCEEDED
    assert action.status is ExternalActionStatus.SUCCEEDED
    assert call is not None and call.status is ToolCallStatus.SUCCEEDED
    await engine.dispose()


@pytest.mark.asyncio
async def test_reconciliation_retry_survives_deadline_and_exhausts_to_manual_review() -> None:
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
        session.add(
            ToolDefinitionRow(
                id=side_tool_id,
                name="reconcile_budget",
                description="write",
            )
        )
        await session.flush()
        session.add(
            ToolVersionRow(
                id=side_version_id,
                tool_id=side_tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.WRITE,
                implementation_ref="tests:reconcile_budget",
                allow_no_approval_execution=True,
                reconciliation_mode=ReconciliationMode.AUTHORITATIVE,
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
                tool_alias="reconcile_budget",
            )
        )

    async def ambiguous(_invocation):
        raise ToolAdapterError(
            "maybe committed",
            error_class="TIMEOUT",
            definite_not_executed=False,
        )

    async def reconcile(_invocation):
        raise RuntimeError("reconciliation transport 503")

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
                name="reconcile_budget",
                description="write",
                input_schema={"type": "object"},
                func=ambiguous,
                reconcile_func=reconcile,
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="reconciliation safety budget",
        idempotency_key="integration-d3-safety-budget",
        principal_scope="test-user",
    )
    claimed1 = await store.claim_next_run(worker_id="d3-budget-1", lease_seconds=30)
    assert claimed1 is not None
    version = await store.load_agent_version(DEMO_AGENT_VERSION_ID)
    manager1 = RunManager(
        NativeRunner(ScriptedFakeModel([ToolStep("reconcile_budget", {})]), registry),
        ToolCoordinator(registry),
    )
    recorder1 = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed1.execution_generation,
    )
    await manager1.execute(
        run=claimed1,
        run_state=await store.load_run_state(created.id),
        agent_version=version,
        recorder=recorder1,
    )

    async with sessions() as session, session.begin():
        row = await session.get(RunRow, created.id)
        assert row is not None
        row.deadline_at = datetime.now(UTC) - timedelta(seconds=1)

    await manager1.execute(
        run=claimed1,
        run_state=await store.load_run_state(created.id),
        agent_version=version,
        recorder=recorder1,
    )
    after_first_reconcile = await store.get_run(created.id)
    assert after_first_reconcile is not None
    assert after_first_reconcile.status is RunStatus.QUEUED
    assert after_first_reconcile.queue_reason is QueueReason.RETRY

    claimed2 = await store.claim_next_run(worker_id="d3-budget-2", lease_seconds=30)
    assert claimed2 is not None
    recorder2 = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed2.execution_generation,
    )
    manager2 = RunManager(
        NativeRunner(ScriptedFakeModel([FinalStep("must not reason")]), registry),
        ToolCoordinator(registry),
    )
    await manager2.execute(
        run=claimed2,
        run_state=await store.load_run_state(created.id),
        agent_version=version,
        recorder=recorder2,
    )

    durable = await store.get_run(created.id)
    assert durable is not None
    assert durable.status is RunStatus.WAITING_ACTION_RESOLUTION
    async with sessions() as session:
        attempts = (
            (
                await session.execute(
                    select(ReconciliationAttemptRow).order_by(
                        ReconciliationAttemptRow.attempt_number
                    )
                )
            )
            .scalars()
            .all()
        )
        action = (await session.execute(select(ExternalActionRow))).scalar_one()
    assert [item.attempt_number for item in attempts] == [1, 2]
    assert all(item.status is ReconciliationAttemptStatus.FAILED for item in attempts)
    assert action.status is ExternalActionStatus.MANUAL_REVIEW
    await engine.dispose()


@pytest.mark.asyncio
async def test_orphaned_reconciliation_attempt_closes_failed_and_preserves_truth() -> None:
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
        session.add(
            ToolDefinitionRow(
                id=side_tool_id,
                name="orphan_reconcile",
                description="write",
            )
        )
        await session.flush()
        session.add(
            ToolVersionRow(
                id=side_version_id,
                tool_id=side_tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.WRITE,
                implementation_ref="tests:orphan_reconcile",
                allow_no_approval_execution=True,
                reconciliation_mode=ReconciliationMode.AUTHORITATIVE,
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
                tool_alias="orphan_reconcile",
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
                name="orphan_reconcile",
                description="write",
                input_schema={"type": "object"},
                func=lambda invocation: {"unused": True},
                reconcile_func=lambda invocation: ReconciliationResult(
                    ReconciliationBusinessResult.UNKNOWN
                ),
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="orphan reconciliation",
        idempotency_key="integration-d3-orphan-reconcile",
        principal_scope="test-user",
    )
    claimed1 = await store.claim_next_run(worker_id="d3-orphan-1", lease_seconds=30)
    assert claimed1 is not None
    recorder1 = PostgresExecutionRecorder(
        sessions,
        run_id=created.id,
        generation=claimed1.execution_generation,
    )
    version = await store.load_agent_version(DEMO_AGENT_VERSION_ID)

    _, invocation = await recorder1.begin_model_invocation(
        run_id=created.id,
        invocation_id=uuid4(),
        expected_generation=claimed1.execution_generation,
    )
    invocation.complete("TOOL_PROPOSAL")
    proposal = ToolProposal.create(
        run_id=created.id,
        model_invocation_id=invocation.id,
        tool_name="orphan_reconcile",
        arguments={"v": 1},
    )
    prepared = ToolCoordinator(registry).prepare_side_effect(
        proposal=proposal,
        agent_version=version,
    )
    await recorder1.record_model_side_effect_prepared(
        invocation,
        proposal,
        prepared.call,
        prepared.snapshot,
        prepared.action,
        expected_generation=claimed1.execution_generation,
    )
    physical = await recorder1.record_side_effect_attempt_started(
        prepared.call,
        prepared.action,
        expected_generation=claimed1.execution_generation,
    )
    await recorder1.record_side_effect_unknown(
        prepared.call,
        prepared.action,
        physical,
        error="ambiguous",
        error_class="TIMEOUT",
        outcome_reason="SIDE_EFFECT_POSSIBLE_EXECUTION",
        expected_generation=claimed1.execution_generation,
    )
    unresolved = await recorder1.load_reconciliation_external_action(created.id)
    assert unresolved is not None
    call, _snapshot, action = unresolved
    recon_attempt = await recorder1.record_reconciliation_started(
        call,
        action,
        claimed1,
        max_attempts=2,
        expected_generation=claimed1.execution_generation,
    )
    assert recon_attempt is not None

    async with sessions() as session, session.begin():
        row = await session.get(RunRow, created.id)
        assert row is not None
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)

    claimed2 = await store.claim_next_run(worker_id="d3-orphan-2", lease_seconds=30)
    assert claimed2 is not None
    async with sessions() as session:
        durable_attempt = await session.get(ReconciliationAttemptRow, recon_attempt.id)
        durable_action = (await session.execute(select(ExternalActionRow))).scalar_one()
    assert durable_attempt is not None
    assert durable_attempt.status is ReconciliationAttemptStatus.FAILED
    assert durable_attempt.outcome_reason == "LEASE_LOST"
    assert durable_action.status is ExternalActionStatus.RECONCILING
    assert durable_action.current_attempt_id is None
    await engine.dispose()
