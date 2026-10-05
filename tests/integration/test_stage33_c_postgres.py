# ruff: noqa: E402

import os
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select

REQUIRE_POSTGRES = os.getenv("AGENTFORGE_REQUIRE_POSTGRES_INTEGRATION") == "1"
try:
    import psycopg  # noqa: F401
except ImportError as exc:
    if REQUIRE_POSTGRES:
        raise RuntimeError("psycopg is required for Stage 3.3-C acceptance") from exc
    pytest.skip("psycopg is not installed", allow_module_level=True)

DATABASE_URL = os.getenv("AGENTFORGE_TEST_DATABASE_URL")
if not DATABASE_URL:
    if REQUIRE_POSTGRES:
        raise RuntimeError("AGENTFORGE_TEST_DATABASE_URL is required for Stage 3.3-C acceptance")
    pytest.skip("set AGENTFORGE_TEST_DATABASE_URL", allow_module_level=True)

from agentforge.application.errors import BusinessProgressionBlockedError, StaleExecutorError
from agentforge.application.governed_consequence import plan_governed_tool_consequence
from agentforge.domain.enums import (
    ApprovalRequestStatus,
    EventType,
    ExternalActionStatus,
    GovernanceDecision,
    GovernanceMode,
    PrincipalType,
    RunStatus,
    ToolCallStatus,
    ToolEffectType,
)
from agentforge.domain.governance import (
    GovernanceApprovalRequirement,
    GovernancePolicyRule,
    PrincipalContext,
)
from agentforge.domain.models import ToolProposal
from agentforge.infrastructure.db.approval_review_store import PostgresApprovalReviewStore
from agentforge.infrastructure.db.execution_recorder import PostgresExecutionRecorder
from agentforge.infrastructure.db.governance_store import PostgresGovernancePolicyStore
from agentforge.infrastructure.db.models import (
    ActionSnapshotRow,
    AgentRow,
    AgentVersionRow,
    AgentVersionToolRow,
    ApprovalRequestRow,
    DomainEventRow,
    ExternalActionRow,
    GovernanceIntentRow,
    PolicyDecisionRow,
    RunRow,
    ToolCallRow,
    ToolDefinitionRow,
    ToolExecutionAttemptRow,
    ToolProposalRow,
    ToolVersionRow,
)
from agentforge.infrastructure.db.runtime_store import PostgresRuntimeStore
from agentforge.infrastructure.db.session import create_engine, create_session_factory
from agentforge.runtime.tool_coordinator import ToolCoordinator
from agentforge.runtime.tools import FunctionTool, InMemoryToolRegistry, SideEffectFunctionTool


def _config() -> Config:
    config = Config("alembic.ini")
    config.attributes["agentforge_explicit_database_url"] = DATABASE_URL
    config.set_main_option("sqlalchemy.url", DATABASE_URL)
    return config


def _reset_head() -> None:
    config = _config()
    command.downgrade(config, "base")
    command.upgrade(config, "head")


@dataclass(frozen=True, slots=True)
class ApprovalFixture:
    engine: object
    sessions: object
    store: PostgresRuntimeStore
    recorder: PostgresExecutionRecorder
    claimed: object
    invocation: object
    proposal: ToolProposal
    policy: object
    agent_version: object
    tools: ToolCoordinator
    tool_version_id: UUID
    physical_calls: list[str]


async def _fixture(*, effect_type: ToolEffectType) -> ApprovalFixture:
    _reset_head()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    policy_store = PostgresGovernancePolicyStore(sessions)

    agent_id = uuid4()
    agent_version_id = uuid4()
    tool_id = uuid4()
    tool_version_id = uuid4()
    tool_name = "lookup" if effect_type is ToolEffectType.READ else "governed_effect"

    rule = GovernancePolicyRule(
        rule_id="c-require-approval",
        priority=100,
        decision=GovernanceDecision.REQUIRE_APPROVAL,
        approval=GovernanceApprovalRequirement(
            required_approver_role="risk-approver",
            separation_of_duties=True,
            ttl_seconds=600,
        ),
    )
    draft = await policy_store.create_draft(
        policy_key=f"c-policy-{uuid4()}",
        version_number=1,
        rules=(rule,),
    )
    policy = await policy_store.publish(draft.id)

    async with sessions() as session, session.begin():
        session.add_all(
            [
                AgentRow(id=agent_id, name=f"c-agent-{agent_id}", description=""),
                ToolDefinitionRow(id=tool_id, name=f"{tool_name}-{tool_id}", description=""),
            ]
        )
        await session.flush()
        session.add_all(
            [
                ToolVersionRow(
                    id=tool_version_id,
                    tool_id=tool_id,
                    version_number=1,
                    input_schema={"type": "object"},
                    effect_type=effect_type,
                    implementation_ref=f"test://{tool_name}",
                    credential_ref=(
                        "credential://ticket-service"
                        if effect_type is not ToolEffectType.READ
                        else None
                    ),
                ),
                AgentVersionRow(
                    id=agent_version_id,
                    agent_id=agent_id,
                    version_number=1,
                    instructions="Stage 3.3-C governed approval fixture",
                    governance_mode=GovernanceMode.GOVERNED,
                    policy_version_id=policy.id,
                ),
            ]
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=agent_version_id,
                tool_version_id=tool_version_id,
                tool_alias=tool_name,
            )
        )

    principal = PrincipalContext(
        principal_id="requester-c",
        principal_type=PrincipalType.USER,
        roles=("operator", "runtime:run:create"),
        principal_scope="tenant-c",
        authn_source="test-oidc",
    )
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=agent_version_id,
        input_text="approval-required request",
        idempotency_key=f"stage33-c-{uuid4()}",
        principal_scope="ignored",
        principal=principal,
    )
    claimed = await store.claim_next_run(worker_id="stage33-c-worker", lease_seconds=30)
    assert claimed is not None
    assert claimed.id == created.id

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
    invocation.complete("TOOL_PROPOSAL")
    proposal = ToolProposal.create(
        run_id=claimed.id,
        model_invocation_id=invocation.id,
        tool_name=tool_name,
        arguments=(
            {"q": "hello"}
            if effect_type is ToolEffectType.READ
            else {"ticket": "exact pre-effect identity"}
        ),
    )

    physical_calls: list[str] = []
    if effect_type is ToolEffectType.READ:
        registry = InMemoryToolRegistry(
            [
                FunctionTool(
                    version_id=tool_version_id,
                    name=tool_name,
                    description="read",
                    input_schema={"type": "object"},
                    func=lambda **kwargs: physical_calls.append(str(kwargs)) or {"ok": True},
                )
            ]
        )
    else:
        registry = InMemoryToolRegistry(
            [
                SideEffectFunctionTool(
                    version_id=tool_version_id,
                    name=tool_name,
                    description="effect",
                    input_schema={"type": "object"},
                    func=lambda invocation: (
                        physical_calls.append(str(invocation.operation_id)) or {"ok": True}
                    ),
                )
            ]
        )

    agent_version = await store.load_agent_version(agent_version_id)
    return ApprovalFixture(
        engine=engine,
        sessions=sessions,
        store=store,
        recorder=recorder,
        claimed=claimed,
        invocation=invocation,
        proposal=proposal,
        policy=policy,
        agent_version=agent_version,
        tools=ToolCoordinator(registry),
        tool_version_id=tool_version_id,
        physical_calls=physical_calls,
    )


async def _persist_pending(fx: ApprovalFixture):
    plan = plan_governed_tool_consequence(
        run=fx.claimed,
        agent_version=fx.agent_version,
        proposal=fx.proposal,
        policy=fx.policy,
        tools=fx.tools,
    )
    assert plan.pending_call is not None
    if plan.pending_action is None:
        await fx.recorder.record_governed_model_read_approval_pending(
            fx.invocation,
            fx.proposal,
            plan.pending_call,
            plan.intent,
            plan.evaluation,
            fx.policy.id,
            expected_generation=fx.claimed.execution_generation,
        )
    else:
        assert plan.pending_snapshot is not None
        await fx.recorder.record_governed_model_side_effect_approval_pending(
            fx.invocation,
            fx.proposal,
            plan.pending_call,
            plan.pending_snapshot,
            plan.pending_action,
            plan.intent,
            plan.evaluation,
            fx.policy.id,
            expected_generation=fx.claimed.execution_generation,
        )
    return plan


@pytest.mark.asyncio
async def test_c_read_require_approval_atomically_enters_waiting_with_zero_io() -> None:
    fx = await _fixture(effect_type=ToolEffectType.READ)
    plan = plan_governed_tool_consequence(
        run=fx.claimed,
        agent_version=fx.agent_version,
        proposal=fx.proposal,
        policy=fx.policy,
        tools=fx.tools,
    )
    assert plan.pending_call is not None
    assert plan.pending_snapshot is None
    assert plan.pending_action is None

    state = await fx.recorder.record_governed_model_read_approval_pending(
        fx.invocation,
        fx.proposal,
        plan.pending_call,
        plan.intent,
        plan.evaluation,
        fx.policy.id,
        expected_generation=fx.claimed.execution_generation,
    )

    assert fx.physical_calls == []
    assert state.tool_call_count == 1
    assert state.tool_attempts_used == 0

    async with fx.sessions() as session:
        run = await session.get(RunRow, fx.claimed.id)
        request = (
            await session.execute(
                select(ApprovalRequestRow).where(ApprovalRequestRow.run_id == fx.claimed.id)
            )
        ).scalar_one()
        call = (
            await session.execute(select(ToolCallRow).where(ToolCallRow.run_id == fx.claimed.id))
        ).scalar_one()
        decision = (
            await session.execute(
                select(PolicyDecisionRow).where(PolicyDecisionRow.run_id == fx.claimed.id)
            )
        ).scalar_one()
        intent = (
            await session.execute(
                select(GovernanceIntentRow).where(GovernanceIntentRow.run_id == fx.claimed.id)
            )
        ).scalar_one()
        attempt_count = await session.scalar(
            select(func.count())
            .select_from(ToolExecutionAttemptRow)
            .where(ToolExecutionAttemptRow.run_id == fx.claimed.id)
        )
        action_count = await session.scalar(
            select(func.count())
            .select_from(ExternalActionRow)
            .where(ExternalActionRow.run_id == fx.claimed.id)
        )
        events = (
            (
                await session.execute(
                    select(DomainEventRow.event_type)
                    .where(DomainEventRow.run_id == fx.claimed.id)
                    .order_by(DomainEventRow.sequence)
                )
            )
            .scalars()
            .all()
        )

    assert run is not None
    assert run.status is RunStatus.WAITING_APPROVAL
    assert run.owner_worker_id is None
    assert run.lease_expires_at is None
    assert call.status is ToolCallStatus.AWAITING_APPROVAL
    assert decision.effective_decision is GovernanceDecision.REQUIRE_APPROVAL
    assert request.status is ApprovalRequestStatus.PENDING
    assert request.external_action_id is None
    assert request.action_snapshot_digest is None
    assert request.policy_decision_id == decision.id
    assert request.governance_intent_digest == intent.digest
    assert request.required_approver_role == "risk-approver"
    assert request.separation_of_duties is True
    assert request.created_at < request.expires_at <= run.deadline_at
    assert attempt_count == 0
    assert action_count == 0
    assert EventType.APPROVAL_REQUESTED.value in events
    await fx.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "effect_type",
    [ToolEffectType.EXTERNAL_SIDE_EFFECT, ToolEffectType.DESTRUCTIVE],
)
async def test_c_side_effect_require_approval_freezes_exact_action_identity(
    effect_type: ToolEffectType,
) -> None:
    fx = await _fixture(effect_type=effect_type)
    plan = plan_governed_tool_consequence(
        run=fx.claimed,
        agent_version=fx.agent_version,
        proposal=fx.proposal,
        policy=fx.policy,
        tools=fx.tools,
    )
    assert plan.pending_call is not None
    assert plan.pending_snapshot is not None
    assert plan.pending_action is not None

    state = await fx.recorder.record_governed_model_side_effect_approval_pending(
        fx.invocation,
        fx.proposal,
        plan.pending_call,
        plan.pending_snapshot,
        plan.pending_action,
        plan.intent,
        plan.evaluation,
        fx.policy.id,
        expected_generation=fx.claimed.execution_generation,
    )

    assert fx.physical_calls == []
    assert state.tool_call_count == 1
    assert state.tool_attempts_used == 0

    async with fx.sessions() as session:
        run = await session.get(RunRow, fx.claimed.id)
        call = (
            await session.execute(select(ToolCallRow).where(ToolCallRow.run_id == fx.claimed.id))
        ).scalar_one()
        action = (
            await session.execute(
                select(ExternalActionRow).where(ExternalActionRow.run_id == fx.claimed.id)
            )
        ).scalar_one()
        snapshot = await session.get(ActionSnapshotRow, action.action_snapshot_id)
        request = (
            await session.execute(
                select(ApprovalRequestRow).where(ApprovalRequestRow.run_id == fx.claimed.id)
            )
        ).scalar_one()
        decision = (
            await session.execute(
                select(PolicyDecisionRow).where(PolicyDecisionRow.run_id == fx.claimed.id)
            )
        ).scalar_one()
        attempt_count = await session.scalar(
            select(func.count())
            .select_from(ToolExecutionAttemptRow)
            .where(ToolExecutionAttemptRow.run_id == fx.claimed.id)
        )

    assert run is not None and run.status is RunStatus.WAITING_APPROVAL
    assert run.owner_worker_id is None
    assert run.lease_expires_at is None
    assert call.status is ToolCallStatus.AWAITING_APPROVAL
    assert action.status is ExternalActionStatus.AWAITING_APPROVAL
    assert action.current_attempt_id is None
    assert snapshot is not None
    assert snapshot.operation_id == action.operation_id
    assert snapshot.tool_version_id == fx.tool_version_id
    assert snapshot.effect_type is effect_type
    assert request.status is ApprovalRequestStatus.PENDING
    assert request.external_action_id == action.id
    assert request.policy_decision_id == decision.id
    assert request.governance_intent_digest == plan.intent.digest
    assert request.action_snapshot_digest == snapshot.digest
    assert attempt_count == 0
    await fx.engine.dispose()


@pytest.mark.asyncio
async def test_c_cancel_before_pending_consequence_rolls_back_candidate_facts() -> None:
    fx = await _fixture(effect_type=ToolEffectType.READ)
    plan = plan_governed_tool_consequence(
        run=fx.claimed,
        agent_version=fx.agent_version,
        proposal=fx.proposal,
        policy=fx.policy,
        tools=fx.tools,
    )
    assert plan.pending_call is not None

    cancelled = await fx.store.cancel_run(fx.claimed.id)
    assert cancelled.cancel_requested is True

    with pytest.raises(BusinessProgressionBlockedError) as exc_info:
        await fx.recorder.record_governed_model_read_approval_pending(
            fx.invocation,
            fx.proposal,
            plan.pending_call,
            plan.intent,
            plan.evaluation,
            fx.policy.id,
            expected_generation=fx.claimed.execution_generation,
        )
    assert exc_info.value.code == "CANCEL_REQUESTED"

    async with fx.sessions() as session:
        proposal_count = await session.scalar(select(func.count()).select_from(ToolProposalRow))
        intent_count = await session.scalar(select(func.count()).select_from(GovernanceIntentRow))
        decision_count = await session.scalar(select(func.count()).select_from(PolicyDecisionRow))
        request_count = await session.scalar(select(func.count()).select_from(ApprovalRequestRow))
        call_count = await session.scalar(select(func.count()).select_from(ToolCallRow))
        attempt_count = await session.scalar(
            select(func.count()).select_from(ToolExecutionAttemptRow)
        )

    assert proposal_count == 0
    assert intent_count == 0
    assert decision_count == 0
    assert request_count == 0
    assert call_count == 0
    assert attempt_count == 0
    assert fx.physical_calls == []
    await fx.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "effect_type",
    [ToolEffectType.READ, ToolEffectType.DESTRUCTIVE],
)
async def test_c_waiting_approval_survives_restart_and_is_not_worker_recoverable(
    effect_type: ToolEffectType,
) -> None:
    fx = await _fixture(effect_type=effect_type)
    await _persist_pending(fx)

    restarted_store = PostgresRuntimeStore(fx.sessions)
    durable = await restarted_store.get_run(fx.claimed.id)
    assert durable is not None
    assert durable.status is RunStatus.WAITING_APPROVAL
    assert durable.owner_worker_id is None
    assert durable.lease_expires_at is None

    claimed = await restarted_store.claim_next_run(
        worker_id="stage33-c-restart-worker",
        lease_seconds=30,
    )
    assert claimed is None

    restarted_recorder = PostgresExecutionRecorder(
        fx.sessions,
        run_id=fx.claimed.id,
        generation=fx.claimed.execution_generation,
    )
    assert await restarted_recorder.load_recoverable_read_call(fx.claimed.id) is None
    assert await restarted_recorder.load_ready_external_action(fx.claimed.id) is None

    with pytest.raises(StaleExecutorError):
        await restarted_recorder.begin_model_invocation(
            run_id=fx.claimed.id,
            invocation_id=uuid4(),
            expected_generation=fx.claimed.execution_generation,
        )

    assert fx.physical_calls == []
    await fx.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "effect_type",
    [ToolEffectType.READ, ToolEffectType.DESTRUCTIVE],
)
async def test_c_cancel_pending_approval_atomically_stabilizes_governance(
    effect_type: ToolEffectType,
) -> None:
    fx = await _fixture(effect_type=effect_type)
    await _persist_pending(fx)

    cancelled = await fx.store.cancel_run(fx.claimed.id)
    assert cancelled.status is RunStatus.CANCELLED
    assert cancelled.cancel_requested is True
    assert cancelled.owner_worker_id is None
    assert cancelled.lease_expires_at is None

    async with fx.sessions() as session:
        request = (
            await session.execute(
                select(ApprovalRequestRow).where(ApprovalRequestRow.run_id == fx.claimed.id)
            )
        ).scalar_one()
        call = (
            await session.execute(select(ToolCallRow).where(ToolCallRow.run_id == fx.claimed.id))
        ).scalar_one()
        action = (
            await session.execute(
                select(ExternalActionRow).where(ExternalActionRow.run_id == fx.claimed.id)
            )
        ).scalar_one_or_none()
        attempt_count = await session.scalar(
            select(func.count())
            .select_from(ToolExecutionAttemptRow)
            .where(ToolExecutionAttemptRow.run_id == fx.claimed.id)
        )

    assert request.status is ApprovalRequestStatus.CANCELLED
    assert request.decided_at is not None
    assert call.status is ToolCallStatus.NOT_EXECUTED
    assert attempt_count == 0
    if effect_type is ToolEffectType.READ:
        assert action is None
    else:
        assert action is not None
        assert action.status is ExternalActionStatus.ABORTED
        assert action.current_attempt_id is None

    again = await fx.store.cancel_run(fx.claimed.id)
    assert again.status is RunStatus.CANCELLED
    assert fx.physical_calls == []
    await fx.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "effect_type",
    [ToolEffectType.READ, ToolEffectType.DESTRUCTIVE],
)
async def test_c_pending_approval_review_projection_is_deterministic_from_durable_facts(
    effect_type: ToolEffectType,
) -> None:
    fx = await _fixture(effect_type=effect_type)
    plan = await _persist_pending(fx)

    async with fx.sessions() as session:
        request_id = await session.scalar(
            select(ApprovalRequestRow.id).where(ApprovalRequestRow.run_id == fx.claimed.id)
        )
    assert request_id is not None

    store = PostgresApprovalReviewStore(fx.sessions)
    first = await store.get_pending(request_id)
    second = await store.get_pending(request_id)
    assert first is not None
    assert first == second
    assert first.run_id == fx.claimed.id
    assert first.tool_call_id == plan.pending_call.id
    assert first.policy_version_id == fx.policy.id
    assert first.governance_intent_digest == plan.intent.digest
    assert first.requested_by_principal == "requester-c"
    assert first.principal_scope == "tenant-c"
    assert first.required_approver_role == "risk-approver"
    assert first.separation_of_duties is True
    assert first.status is ApprovalRequestStatus.PENDING
    assert first.tool_version_id == fx.tool_version_id
    assert first.effect_type is effect_type
    assert first.arguments_canonical_json

    if effect_type is ToolEffectType.READ:
        assert first.external_action_id is None
        assert first.action_snapshot_digest is None
        assert first.operation_id is None
    else:
        assert plan.pending_action is not None
        assert plan.pending_snapshot is not None
        assert first.external_action_id == plan.pending_action.id
        assert first.action_snapshot_digest == plan.pending_snapshot.digest
        assert first.operation_id == plan.pending_action.operation_id

    await fx.store.cancel_run(fx.claimed.id)
    assert await store.get_pending(request_id) is None
    assert fx.physical_calls == []
    await fx.engine.dispose()
