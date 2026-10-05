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
        raise RuntimeError("psycopg is required for Stage 3.3-B acceptance") from exc
    pytest.skip("psycopg is not installed", allow_module_level=True)

DATABASE_URL = os.getenv("AGENTFORGE_TEST_DATABASE_URL")
if not DATABASE_URL:
    if REQUIRE_POSTGRES:
        raise RuntimeError("AGENTFORGE_TEST_DATABASE_URL is required for Stage 3.3-B acceptance")
    pytest.skip("set AGENTFORGE_TEST_DATABASE_URL", allow_module_level=True)

from agentforge.application.errors import BusinessProgressionBlockedError
from agentforge.application.governed_consequence import plan_governed_tool_consequence
from agentforge.domain.enums import (
    EventType,
    ExternalActionStatus,
    GovernanceDecision,
    GovernanceMode,
    PrincipalType,
    RunStatus,
    ToolCallStatus,
    ToolEffectType,
    ToolExecutionAttemptStatus,
)
from agentforge.domain.governance import GovernancePolicyRule, PrincipalContext
from agentforge.domain.models import ToolProposal
from agentforge.infrastructure.db.execution_recorder import PostgresExecutionRecorder
from agentforge.infrastructure.db.governance_store import PostgresGovernancePolicyStore
from agentforge.infrastructure.db.models import (
    AgentRow,
    AgentVersionRow,
    AgentVersionToolRow,
    DomainEventRow,
    ExternalActionRow,
    GovernanceIntentRow,
    ModelInvocationRow,
    PolicyDecisionRow,
    RunRow,
    RunStateRow,
    ToolCallRow,
    ToolDefinitionRow,
    ToolExecutionAttemptRow,
    ToolProposalRow,
    ToolVersionRow,
)
from agentforge.infrastructure.db.runtime_store import PostgresRuntimeStore
from agentforge.infrastructure.db.session import create_engine, create_session_factory
from agentforge.runtime.tool_coordinator import PreparedExternalAction, PreparedToolCall, ToolCoordinator
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
class GovernedFixture:
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


async def _fixture(
    *,
    decision: GovernanceDecision,
    effect_type: ToolEffectType = ToolEffectType.READ,
    allow_no_approval_execution: bool = False,
) -> GovernedFixture:
    _reset_head()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    policy_store = PostgresGovernancePolicyStore(sessions)

    agent_id = uuid4()
    agent_version_id = uuid4()
    tool_id = uuid4()
    tool_version_id = uuid4()
    tool_name = "lookup" if effect_type is ToolEffectType.READ else "create_ticket"

    rule = GovernancePolicyRule(
        rule_id="b-rule",
        priority=100,
        decision=decision,
    )
    draft = await policy_store.create_draft(
        policy_key=f"b-policy-{uuid4()}",
        version_number=1,
        rules=(rule,),
    )
    policy = await policy_store.publish(draft.id)

    async with sessions() as session, session.begin():
        session.add_all(
            [
                AgentRow(id=agent_id, name=f"b-agent-{agent_id}", description=""),
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
                    allow_no_approval_execution=allow_no_approval_execution,
                ),
                AgentVersionRow(
                    id=agent_version_id,
                    agent_id=agent_id,
                    version_number=1,
                    instructions="Stage 3.3-B governed fixture",
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
        principal_id="user-b",
        principal_type=PrincipalType.USER,
        roles=("runtime:run:create", "operator"),
        principal_scope="tenant-b",
        authn_source="test-oidc",
    )
    store = PostgresRuntimeStore(sessions)
    created = await store.create_run(
        agent_version_id=agent_version_id,
        input_text="governed consequence",
        idempotency_key=f"stage33-b-{uuid4()}",
        principal_scope="ignored-body-scope",
        principal=principal,
    )
    claimed = await store.claim_next_run(worker_id="stage33-b-worker", lease_seconds=30)
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
        arguments={"q": "hello"} if effect_type is ToolEffectType.READ else {"summary": "hello"},
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
                    description="side effect",
                    input_schema={"type": "object"},
                    func=lambda invocation: physical_calls.append(str(invocation.operation_id))
                    or {"ok": True},
                )
            ]
        )

    agent_version = await store.load_agent_version(agent_version_id)
    return GovernedFixture(
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


@pytest.mark.asyncio
async def test_b_read_allow_atomically_persists_policy_and_started_before_io() -> None:
    fx = await _fixture(decision=GovernanceDecision.ALLOW)
    plan = plan_governed_tool_consequence(
        run=fx.claimed,
        agent_version=fx.agent_version,
        proposal=fx.proposal,
        policy=fx.policy,
        tools=fx.tools,
    )
    assert isinstance(plan.prepared, PreparedToolCall)

    state = await fx.recorder.record_governed_model_read_allowed_started(
        fx.invocation,
        fx.proposal,
        plan.prepared.call,
        plan.intent,
        plan.evaluation,
        fx.policy.id,
        expected_generation=fx.claimed.execution_generation,
    )

    assert fx.physical_calls == []
    assert state.tool_call_count == 1
    assert state.tool_attempts_used == 1

    async with fx.sessions() as session:
        intent_count = await session.scalar(select(func.count()).select_from(GovernanceIntentRow))
        decision = (
            await session.execute(
                select(PolicyDecisionRow).where(PolicyDecisionRow.proposal_id == fx.proposal.id)
            )
        ).scalar_one()
        call = (
            await session.execute(
                select(ToolCallRow).where(ToolCallRow.proposal_id == fx.proposal.id)
            )
        ).scalar_one()
        attempts = (
            (
                await session.execute(
                    select(ToolExecutionAttemptRow).where(
                        ToolExecutionAttemptRow.tool_call_id == call.id
                    )
                )
            )
            .scalars()
            .all()
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

    assert intent_count == 1
    assert decision.effective_decision is GovernanceDecision.ALLOW
    assert call.status is ToolCallStatus.EXECUTING
    assert call.tool_version_id == fx.tool_version_id
    assert len(attempts) == 1
    assert attempts[0].status is ToolExecutionAttemptStatus.STARTED
    assert attempts[0].execution_generation == fx.claimed.execution_generation
    assert EventType.POLICY_DECIDED.value in events
    assert events.index(EventType.POLICY_DECIDED.value) < events.index(EventType.TOOL_STARTED.value)
    await fx.engine.dispose()


@pytest.mark.asyncio
async def test_b_side_effect_allow_prepares_action_without_physical_attempt() -> None:
    fx = await _fixture(
        decision=GovernanceDecision.ALLOW,
        effect_type=ToolEffectType.EXTERNAL_SIDE_EFFECT,
        allow_no_approval_execution=True,
    )
    plan = plan_governed_tool_consequence(
        run=fx.claimed,
        agent_version=fx.agent_version,
        proposal=fx.proposal,
        policy=fx.policy,
        tools=fx.tools,
    )
    assert isinstance(plan.prepared, PreparedExternalAction)

    state = await fx.recorder.record_governed_model_side_effect_allowed_prepared(
        fx.invocation,
        fx.proposal,
        plan.prepared.call,
        plan.prepared.snapshot,
        plan.prepared.action,
        plan.intent,
        plan.evaluation,
        fx.policy.id,
        expected_generation=fx.claimed.execution_generation,
    )

    assert fx.physical_calls == []
    assert state.tool_call_count == 1
    assert state.tool_attempts_used == 0

    async with fx.sessions() as session:
        decision = (
            await session.execute(
                select(PolicyDecisionRow).where(PolicyDecisionRow.proposal_id == fx.proposal.id)
            )
        ).scalar_one()
        call = (
            await session.execute(
                select(ToolCallRow).where(ToolCallRow.proposal_id == fx.proposal.id)
            )
        ).scalar_one()
        action = (
            await session.execute(
                select(ExternalActionRow).where(ExternalActionRow.tool_call_id == call.id)
            )
        ).scalar_one()
        attempt_count = await session.scalar(
            select(func.count())
            .select_from(ToolExecutionAttemptRow)
            .where(ToolExecutionAttemptRow.run_id == fx.claimed.id)
        )

    assert decision.effective_decision is GovernanceDecision.ALLOW
    assert call.status is ToolCallStatus.READY
    assert action.status is ExternalActionStatus.READY
    assert action.current_attempt_id is None
    assert attempt_count == 0
    await fx.engine.dispose()


@pytest.mark.asyncio
async def test_b_policy_deny_persists_bound_denial_with_zero_action_and_io() -> None:
    fx = await _fixture(decision=GovernanceDecision.DENY)
    plan = plan_governed_tool_consequence(
        run=fx.claimed,
        agent_version=fx.agent_version,
        proposal=fx.proposal,
        policy=fx.policy,
        tools=fx.tools,
    )
    assert plan.denied_call is not None
    fx.claimed.fail("GOVERNANCE_DENIED")

    await fx.recorder.record_governed_model_tool_denied_and_fail_run(
        fx.invocation,
        fx.proposal,
        plan.denied_call,
        fx.claimed,
        plan.intent,
        plan.evaluation,
        fx.policy.id,
        expected_generation=fx.claimed.execution_generation,
    )

    assert fx.physical_calls == []
    async with fx.sessions() as session:
        run = await session.get(RunRow, fx.claimed.id)
        state = await session.get(RunStateRow, fx.claimed.id)
        decision = (
            await session.execute(
                select(PolicyDecisionRow).where(PolicyDecisionRow.proposal_id == fx.proposal.id)
            )
        ).scalar_one()
        call = (
            await session.execute(
                select(ToolCallRow).where(ToolCallRow.proposal_id == fx.proposal.id)
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

    assert run is not None and run.status is RunStatus.FAILED
    assert state is not None and state.tool_call_count == 1
    assert state.tool_attempts_used == 0
    assert decision.effective_decision is GovernanceDecision.DENY
    assert call.status is ToolCallStatus.DENIED
    assert call.tool_version_id == fx.tool_version_id
    assert attempt_count == 0
    assert action_count == 0
    await fx.engine.dispose()


@pytest.mark.asyncio
async def test_b_cancel_wins_before_consequence_and_rolls_back_policy_business_facts() -> None:
    fx = await _fixture(decision=GovernanceDecision.ALLOW)
    plan = plan_governed_tool_consequence(
        run=fx.claimed,
        agent_version=fx.agent_version,
        proposal=fx.proposal,
        policy=fx.policy,
        tools=fx.tools,
    )
    assert isinstance(plan.prepared, PreparedToolCall)

    cancelled = await fx.store.cancel_run(fx.claimed.id)
    assert cancelled.cancel_requested is True

    with pytest.raises(BusinessProgressionBlockedError) as exc_info:
        await fx.recorder.record_governed_model_read_allowed_started(
            fx.invocation,
            fx.proposal,
            plan.prepared.call,
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
        call_count = await session.scalar(select(func.count()).select_from(ToolCallRow))
        attempt_count = await session.scalar(
            select(func.count()).select_from(ToolExecutionAttemptRow)
        )
        invocation = await session.get(ModelInvocationRow, fx.invocation.id)

    assert proposal_count == 0
    assert intent_count == 0
    assert decision_count == 0
    assert call_count == 0
    assert attempt_count == 0
    assert invocation is not None and invocation.status.value == "STARTED"
    assert fx.physical_calls == []
    await fx.engine.dispose()
