from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}: {old[:180]!r}")
    p.write_text(text.replace(old, new))


def append_once(path: str, marker: str, block: str) -> None:
    p = Path(path)
    text = p.read_text()
    if marker in text:
        raise SystemExit(f"{path}: marker already present: {marker}")
    p.write_text(text + block)


Path("src/agentforge/domain/checkpoints.py").write_text(
    '''from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

CHECKPOINT_SCHEMA_VERSION = 1

# Checkpoints are private acceleration state, never a second source of business
# truth. These keys are rejected recursively so callers cannot accidentally
# persist authority, resolved credentials, or chain-of-thought-like material.
_FORBIDDEN_CHECKPOINT_KEYS = frozenset(
    {
        "action_outcome",
        "cancel_requested",
        "chain_of_thought",
        "external_action_status",
        "reasoning_trace",
        "resolved_credential",
        "resolved_credentials",
        "secret",
        "secrets",
        "tool_call_outcome",
    }
)


def validate_checkpoint_private_payload(value: object, *, path: str = "$") -> None:
    if value is None or isinstance(value, (bool, int, float, str)):
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            validate_checkpoint_private_payload(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"checkpoint object key at {path} must be a string")
            normalized = key.strip().lower()
            if normalized in _FORBIDDEN_CHECKPOINT_KEYS:
                raise ValueError(
                    f"checkpoint payload contains forbidden authoritative/private key: {path}.{key}"
                )
            validate_checkpoint_private_payload(item, path=f"{path}.{key}")
        return
    raise ValueError(f"unsupported checkpoint payload type at {path}: {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class RuntimeCheckpoint:
    run_id: UUID
    schema_version: int
    runner_version: str
    run_state_version: int
    execution_spec_identity: str
    working_state: dict[str, Any]
    message_high_water: int
    event_high_water: int
    context_cursor: dict[str, Any] | None
    created_at: datetime
'''
)

replace_once(
    "src/agentforge/application/ports.py",
    '''from agentforge.domain.actions import ActionResolution, ActionSnapshot, ExternalAction
from agentforge.domain.enums import ActionResolutionOutcome, ReconciliationBusinessResult
''',
    '''from agentforge.domain.actions import ActionResolution, ActionSnapshot, ExternalAction
from agentforge.domain.checkpoints import RuntimeCheckpoint
from agentforge.domain.enums import ActionResolutionOutcome, ReconciliationBusinessResult
''',
)

replace_once(
    "src/agentforge/application/ports.py",
    '''    async def load_agent_version(self, agent_version_id: UUID) -> AgentVersion: ...
''',
    '''    async def load_agent_version(self, agent_version_id: UUID) -> AgentVersion: ...

    async def save_checkpoint(
        self,
        *,
        run_id: UUID,
        expected_generation: int,
        runner_version: str,
        working_state: dict[str, Any],
        context_cursor: dict[str, Any] | None = None,
    ) -> RuntimeCheckpoint: ...

    async def load_checkpoint_overlay(
        self,
        *,
        run_id: UUID,
        runner_version: str,
        supported_schema_version: int = 1,
    ) -> RuntimeCheckpoint | None: ...
''',
)

replace_once(
    "src/agentforge/infrastructure/db/models.py",
    '''class DomainEventRow(Base):
''',
    '''class CheckpointRow(Base):
    __tablename__ = "run_checkpoints"
    __table_args__ = (
        CheckConstraint("schema_version > 0", name="ck_run_checkpoints_positive_schema"),
        CheckConstraint("run_state_version >= 0", name="ck_run_checkpoints_nonnegative_state_version"),
        CheckConstraint("message_high_water >= 0", name="ck_run_checkpoints_nonnegative_message_water"),
        CheckConstraint("event_high_water >= 0", name="ck_run_checkpoints_nonnegative_event_water"),
        CheckConstraint("length(btrim(runner_version)) > 0", name="ck_run_checkpoints_runner_nonblank"),
        CheckConstraint(
            "length(btrim(execution_spec_identity)) > 0",
            name="ck_run_checkpoints_execution_spec_nonblank",
        ),
    )

    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    runner_version: Mapped[str] = mapped_column(String(100), nullable=False)
    run_state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    execution_spec_identity: Mapped[str] = mapped_column(String(300), nullable=False)
    working_state: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    message_high_water: Mapped[int] = mapped_column(Integer, nullable=False)
    event_high_water: Mapped[int] = mapped_column(Integer, nullable=False)
    context_cursor: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class DomainEventRow(Base):
''',
)

Path("migrations/versions/0016_checkpoint_overlay.py").write_text(
    '''"""add optional Checkpoint V1 overlay

Revision ID: 0016_checkpoint_overlay
Revises: 0015_action_resolution
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_checkpoint_overlay"
down_revision: str | None = "0015_action_resolution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "run_checkpoints",
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("runner_version", sa.String(length=100), nullable=False),
        sa.Column("run_state_version", sa.Integer(), nullable=False),
        sa.Column("execution_spec_identity", sa.String(length=300), nullable=False),
        sa.Column("working_state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("message_high_water", sa.Integer(), nullable=False),
        sa.Column("event_high_water", sa.Integer(), nullable=False),
        sa.Column("context_cursor", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "schema_version > 0",
            name="ck_run_checkpoints_positive_schema",
        ),
        sa.CheckConstraint(
            "run_state_version >= 0",
            name="ck_run_checkpoints_nonnegative_state_version",
        ),
        sa.CheckConstraint(
            "message_high_water >= 0",
            name="ck_run_checkpoints_nonnegative_message_water",
        ),
        sa.CheckConstraint(
            "event_high_water >= 0",
            name="ck_run_checkpoints_nonnegative_event_water",
        ),
        sa.CheckConstraint(
            "length(btrim(runner_version)) > 0",
            name="ck_run_checkpoints_runner_nonblank",
        ),
        sa.CheckConstraint(
            "length(btrim(execution_spec_identity)) > 0",
            name="ck_run_checkpoints_execution_spec_nonblank",
        ),
    )


def downgrade() -> None:
    op.drop_table("run_checkpoints")
'''
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''from agentforge.domain.actions import ActionResolution
from agentforge.domain.enums import (
''',
    '''from agentforge.domain.actions import ActionResolution
from agentforge.domain.checkpoints import (
    CHECKPOINT_SCHEMA_VERSION,
    RuntimeCheckpoint,
    validate_checkpoint_private_payload,
)
from agentforge.domain.enums import (
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''    ActionResolutionRow,
    AgentVersionRow,
''',
    '''    ActionResolutionRow,
    AgentVersionRow,
    CheckpointRow,
''',
)

replace_once(
    "src/agentforge/infrastructure/db/runtime_store.py",
    '''    async def claim_next_run(self, *, worker_id: str, lease_seconds: int) -> Run | None:
''',
    '''    async def save_checkpoint(
        self,
        *,
        run_id: UUID,
        expected_generation: int,
        runner_version: str,
        working_state: dict[str, Any],
        context_cursor: dict[str, Any] | None = None,
    ) -> RuntimeCheckpoint:
        """Persist optional private runner state at exact durable high-water marks."""
        if not runner_version.strip():
            raise ValueError("runner_version cannot be blank")
        validate_checkpoint_private_payload(working_state, path="$.working_state")
        if context_cursor is not None:
            validate_checkpoint_private_payload(context_cursor, path="$.context_cursor")

        async with self._sessions() as session, session.begin():
            run_row = (
                await session.execute(
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
            ).scalar_one_or_none()
            if run_row is None:
                raise RuntimeError(
                    f"run {run_id} is not currently owned for checkpoint generation "
                    f"{expected_generation}"
                )
            state = (
                await session.execute(
                    select(RunStateRow)
                    .where(RunStateRow.run_id == run_id)
                    .with_for_update()
                )
            ).scalar_one()
            counter = (
                await session.execute(
                    select(RunCounterRow)
                    .where(RunCounterRow.run_id == run_id)
                    .with_for_update()
                )
            ).scalar_one()
            execution_spec_identity = f"agent-version:{run_row.agent_version_id}"
            stmt = (
                pg_insert(CheckpointRow)
                .values(
                    run_id=run_id,
                    schema_version=CHECKPOINT_SCHEMA_VERSION,
                    runner_version=runner_version.strip(),
                    run_state_version=state.state_version,
                    execution_spec_identity=execution_spec_identity,
                    working_state=working_state,
                    message_high_water=counter.message_sequence,
                    event_high_water=counter.event_sequence,
                    context_cursor=context_cursor,
                    created_at=func.clock_timestamp(),
                )
                .on_conflict_do_update(
                    index_elements=[CheckpointRow.run_id],
                    set_={
                        "schema_version": CHECKPOINT_SCHEMA_VERSION,
                        "runner_version": runner_version.strip(),
                        "run_state_version": state.state_version,
                        "execution_spec_identity": execution_spec_identity,
                        "working_state": working_state,
                        "message_high_water": counter.message_sequence,
                        "event_high_water": counter.event_sequence,
                        "context_cursor": context_cursor,
                        "created_at": func.clock_timestamp(),
                    },
                )
            )
            await session.execute(stmt)
            row = (
                await session.execute(
                    select(CheckpointRow).where(CheckpointRow.run_id == run_id)
                )
            ).scalar_one()
            return RuntimeCheckpoint(
                run_id=row.run_id,
                schema_version=row.schema_version,
                runner_version=row.runner_version,
                run_state_version=row.run_state_version,
                execution_spec_identity=row.execution_spec_identity,
                working_state=dict(row.working_state),
                message_high_water=row.message_high_water,
                event_high_water=row.event_high_water,
                context_cursor=(
                    None if row.context_cursor is None else dict(row.context_cursor)
                ),
                created_at=row.created_at,
            )

    async def load_checkpoint_overlay(
        self,
        *,
        run_id: UUID,
        runner_version: str,
        supported_schema_version: int = CHECKPOINT_SCHEMA_VERSION,
    ) -> RuntimeCheckpoint | None:
        """Return only an exactly compatible/fresh overlay; durable facts always win."""
        if supported_schema_version <= 0:
            raise ValueError("supported_schema_version must be positive")
        if not runner_version.strip():
            raise ValueError("runner_version cannot be blank")

        async with self._sessions() as session, session.begin():
            run_row = (
                await session.execute(
                    select(RunRow).where(RunRow.id == run_id).with_for_update()
                )
            ).scalar_one_or_none()
            if run_row is None:
                raise KeyError(f"run not found: {run_id}")
            checkpoint = await session.get(CheckpointRow, run_id)
            if checkpoint is None:
                return None
            # Terminal/waiting Runs have no autonomous private state to restore.
            if run_row.status not in {RunStatus.QUEUED, RunStatus.RUNNING}:
                return None
            state = await session.get(RunStateRow, run_id)
            counter = await session.get(RunCounterRow, run_id)
            if state is None or counter is None:
                raise RuntimeError("run is missing state/counter rows")
            current_spec = f"agent-version:{run_row.agent_version_id}"
            compatible = (
                checkpoint.schema_version == supported_schema_version
                and checkpoint.runner_version == runner_version.strip()
                and checkpoint.execution_spec_identity == current_spec
            )
            fresh = (
                checkpoint.run_state_version == state.state_version
                and checkpoint.message_high_water == counter.message_sequence
                and checkpoint.event_high_water == counter.event_sequence
            )
            if not compatible or not fresh:
                return None
            return RuntimeCheckpoint(
                run_id=checkpoint.run_id,
                schema_version=checkpoint.schema_version,
                runner_version=checkpoint.runner_version,
                run_state_version=checkpoint.run_state_version,
                execution_spec_identity=checkpoint.execution_spec_identity,
                working_state=dict(checkpoint.working_state),
                message_high_water=checkpoint.message_high_water,
                event_high_water=checkpoint.event_high_water,
                context_cursor=(
                    None
                    if checkpoint.context_cursor is None
                    else dict(checkpoint.context_cursor)
                ),
                created_at=checkpoint.created_at,
            )

    async def claim_next_run(self, *, worker_id: str, lease_seconds: int) -> Run | None:
''',
)

# Tests: model import + CheckpointRow.
replace_once(
    "tests/integration/test_postgres_runtime.py",
    '''    AgentVersionToolRow,
    DomainEventRow,
''',
    '''    AgentVersionToolRow,
    CheckpointRow,
    DomainEventRow,
''',
)

append_once(
    "tests/integration/test_postgres_runtime.py",
    "test_f1_checkpoint_missing_compatible_and_unsupported_fallback",
    r'''


@pytest.mark.asyncio
async def test_f1_checkpoint_missing_compatible_and_unsupported_fallback() -> None:
    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="checkpoint overlay",
        idempotency_key="integration-f1-checkpoint-basic",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="f1-checkpoint", lease_seconds=30)
    assert claimed is not None

    assert (
        await store.load_checkpoint_overlay(
            run_id=created.id,
            runner_version="native-v1",
        )
        is None
    )

    saved = await store.save_checkpoint(
        run_id=created.id,
        expected_generation=claimed.execution_generation,
        runner_version="native-v1",
        working_state={"phase": "before-model", "scratch": {"step": 1}},
        context_cursor={"message": 1},
    )
    loaded = await store.load_checkpoint_overlay(
        run_id=created.id,
        runner_version="native-v1",
    )
    assert loaded == saved
    assert loaded is not None
    assert loaded.working_state == {"phase": "before-model", "scratch": {"step": 1}}

    # Runner/schema mismatch never blocks correctness; it discards the overlay.
    assert (
        await store.load_checkpoint_overlay(
            run_id=created.id,
            runner_version="native-v2",
        )
        is None
    )
    async with sessions() as session, session.begin():
        row = await session.get(CheckpointRow, created.id)
        assert row is not None
        row.schema_version = 99
    assert (
        await store.load_checkpoint_overlay(
            run_id=created.id,
            runner_version="native-v1",
        )
        is None
    )
    await engine.dispose()


@pytest.mark.asyncio
async def test_f1_checkpoint_rejects_authority_secret_and_reasoning_payloads() -> None:
    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="checkpoint forbidden fields",
        idempotency_key="integration-f1-checkpoint-forbidden",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="f1-forbidden", lease_seconds=30)
    assert claimed is not None

    for payload in (
        {"chain_of_thought": "private reasoning"},
        {"nested": {"resolved_credentials": "sentinel-secret"}},
        {"cancel_requested": True},
        {"action_outcome": "SUCCEEDED"},
        {"tool_call_outcome": "FAILED"},
    ):
        with pytest.raises(ValueError, match="forbidden"):
            await store.save_checkpoint(
                run_id=created.id,
                expected_generation=claimed.execution_generation,
                runner_version="native-v1",
                working_state=payload,
            )

    async with sessions() as session:
        assert await session.get(CheckpointRow, created.id) is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_f1_newer_tool_action_attempt_and_reconciliation_facts_stale_checkpoint() -> None:
    from agentforge.domain.enums import ReconciliationMode

    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)

    side_tool_id = uuid4()
    side_version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            ToolDefinitionRow(id=side_tool_id, name="f1_checkpoint_side", description="side")
        )
        await session.flush()
        session.add(
            ToolVersionRow(
                id=side_version_id,
                tool_id=side_tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.EXTERNAL_SIDE_EFFECT,
                implementation_ref="tests:f1_checkpoint_side",
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
                tool_alias="f1_checkpoint_side",
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
                name="f1_checkpoint_side",
                description="side",
                input_schema={"type": "object"},
                func=lambda invocation: {"ok": True},
                reconcile_func=lambda invocation: ReconciliationResult(
                    ReconciliationBusinessResult.UNKNOWN,
                    {"operation_id": str(invocation.operation_id)},
                ),
            ),
        ]
    )
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="checkpoint durable facts",
        idempotency_key="integration-f1-checkpoint-facts",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="f1-facts", lease_seconds=30)
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

    await store.save_checkpoint(
        run_id=created.id,
        expected_generation=claimed.execution_generation,
        runner_version="native-v1",
        working_state={"phase": "model-started"},
    )
    invocation.complete("TOOL_PROPOSAL")
    proposal = ToolProposal.create(
        run_id=created.id,
        model_invocation_id=invocation.id,
        tool_name="f1_checkpoint_side",
        arguments={"v": 1},
    )
    version = await store.load_agent_version(DEMO_AGENT_VERSION_ID)
    prepared = ToolCoordinator(registry).prepare_side_effect(
        proposal=proposal,
        agent_version=version,
    )
    await recorder.record_model_side_effect_prepared(
        invocation,
        proposal,
        prepared.call,
        prepared.snapshot,
        prepared.action,
        expected_generation=claimed.execution_generation,
    )
    assert (
        await store.load_checkpoint_overlay(
            run_id=created.id,
            runner_version="native-v1",
        )
        is None
    )

    await store.save_checkpoint(
        run_id=created.id,
        expected_generation=claimed.execution_generation,
        runner_version="native-v1",
        working_state={"phase": "action-ready"},
    )
    attempt = await recorder.record_side_effect_attempt_started(
        prepared.call,
        prepared.action,
        expected_generation=claimed.execution_generation,
    )
    assert (
        await store.load_checkpoint_overlay(
            run_id=created.id,
            runner_version="native-v1",
        )
        is None
    )

    await recorder.record_side_effect_unknown(
        prepared.call,
        prepared.action,
        attempt,
        error="response lost",
        error_class="RESPONSE_LOST",
        outcome_reason="SIDE_EFFECT_POSSIBLE_EXECUTION",
        expected_generation=claimed.execution_generation,
    )
    await store.save_checkpoint(
        run_id=created.id,
        expected_generation=claimed.execution_generation,
        runner_version="native-v1",
        working_state={"phase": "action-unknown"},
    )
    binding = next(item for item in version.tool_bindings if item.name == "f1_checkpoint_side")
    reconciliation = await recorder.record_reconciliation_started(
        prepared.call,
        prepared.action,
        claimed,
        max_attempts=binding.reconciliation_max_attempts,
        expected_generation=claimed.execution_generation,
    )
    assert reconciliation is not None
    assert (
        await store.load_checkpoint_overlay(
            run_id=created.id,
            runner_version="native-v1",
        )
        is None
    )
    await engine.dispose()


@pytest.mark.asyncio
async def test_f1_newer_cancellation_fact_stales_checkpoint() -> None:
    reset_schema()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    await seed_demo(sessions)
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=DEMO_AGENT_VERSION_ID,
        input_text="checkpoint cancellation",
        idempotency_key="integration-f1-checkpoint-cancel",
        principal_scope="test-user",
    )
    claimed = await store.claim_next_run(worker_id="f1-cancel", lease_seconds=30)
    assert claimed is not None
    await store.save_checkpoint(
        run_id=created.id,
        expected_generation=claimed.execution_generation,
        runner_version="native-v1",
        working_state={"phase": "running"},
    )
    cancelled = await store.cancel_run(created.id)
    assert cancelled.cancel_requested is True
    assert (
        await store.load_checkpoint_overlay(
            run_id=created.id,
            runner_version="native-v1",
        )
        is None
    )
    await engine.dispose()
'''
)
