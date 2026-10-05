from datetime import UTC, datetime
from uuid import uuid4

from agentforge.application.governed_consequence import plan_governed_tool_consequence
from agentforge.domain.enums import (
    GovernanceDecision,
    GovernanceMode,
    GovernancePolicyStatus,
    PrincipalType,
    ToolCallStatus,
    ToolEffectType,
)
from agentforge.domain.governance import (
    GovernanceApprovalRequirement,
    GovernancePolicyRule,
    GovernancePolicyVersion,
)
from agentforge.domain.models import AgentVersion, Run, ToolBinding, ToolProposal
from agentforge.runtime.tool_coordinator import PreparedToolCall, ToolCoordinator
from agentforge.runtime.tools import FunctionTool, InMemoryToolRegistry

NOW = datetime(2026, 10, 5, tzinfo=UTC)


def _fixture(
    decision: GovernanceDecision,
    *,
    approval_required: bool = False,
):
    tool_version_id = uuid4()
    policy_id = uuid4()
    agent_version_id = uuid4()
    run_id = uuid4()
    proposal_id = uuid4()
    invocation_id = uuid4()
    calls: list[dict[str, object]] = []

    def read_tool(**kwargs):
        calls.append(kwargs)
        return {"ok": True}

    registry = InMemoryToolRegistry(
        [
            FunctionTool(
                version_id=tool_version_id,
                name="lookup",
                description="lookup",
                input_schema={"type": "object"},
                func=read_tool,
            )
        ]
    )
    binding = ToolBinding(
        tool_version_id=tool_version_id,
        name="lookup",
        effect_type=ToolEffectType.READ,
        approval_required=approval_required,
    )
    agent_version = AgentVersion(
        id=agent_version_id,
        agent_id=uuid4(),
        version_number=1,
        instructions="governed",
        tool_bindings=(binding,),
        governance_mode=GovernanceMode.GOVERNED,
        policy_version_id=policy_id,
    )
    run = Run(
        id=run_id,
        agent_version_id=agent_version_id,
        input_text="governed request",
        policy_version_id=policy_id,
        requester_principal_id="user-1",
        requester_principal_type=PrincipalType.USER,
        requester_roles=("operator",),
        requester_scope="tenant-a",
        requester_authn_source="test-oidc",
    )
    approval = (
        GovernanceApprovalRequirement(
            required_approver_role="approver",
            separation_of_duties=True,
            ttl_seconds=600,
        )
        if decision is GovernanceDecision.REQUIRE_APPROVAL
        else None
    )
    policy = GovernancePolicyVersion(
        id=policy_id,
        policy_key="b-policy",
        version_number=1,
        status=GovernancePolicyStatus.PUBLISHED,
        rules=(
            GovernancePolicyRule(
                rule_id="rule-1",
                priority=100,
                decision=decision,
                approval=approval,
            ),
        ),
        created_at=NOW,
        published_at=NOW,
    )
    proposal = ToolProposal(
        id=proposal_id,
        run_id=run_id,
        model_invocation_id=invocation_id,
        tool_name="lookup",
        arguments={"q": "hello"},
    )
    return run, agent_version, policy, proposal, ToolCoordinator(registry), calls


def test_governed_read_allow_prepares_stage32_call_without_adapter_io() -> None:
    run, version, policy, proposal, tools, calls = _fixture(GovernanceDecision.ALLOW)

    plan = plan_governed_tool_consequence(
        run=run,
        agent_version=version,
        proposal=proposal,
        policy=policy,
        tools=tools,
    )

    assert plan.evaluation.effective_decision is GovernanceDecision.ALLOW
    assert isinstance(plan.prepared, PreparedToolCall)
    assert plan.prepared.call.status is ToolCallStatus.EXECUTING
    assert plan.prepared.call.tool_version_id == version.tool_bindings[0].tool_version_id
    assert plan.denied_call is None
    assert calls == []


def test_governed_policy_deny_binds_exact_tool_version_and_creates_no_prepared_io() -> None:
    run, version, policy, proposal, tools, calls = _fixture(GovernanceDecision.DENY)

    plan = plan_governed_tool_consequence(
        run=run,
        agent_version=version,
        proposal=proposal,
        policy=policy,
        tools=tools,
    )

    assert plan.evaluation.effective_decision is GovernanceDecision.DENY
    assert plan.prepared is None
    assert plan.denied_call is not None
    assert plan.denied_call.status is ToolCallStatus.DENIED
    assert plan.denied_call.tool_version_id == version.tool_bindings[0].tool_version_id
    assert plan.denied_call.error == "GOVERNANCE_DENIED"
    assert calls == []


def test_governed_require_approval_remains_non_executable_in_stage33_b() -> None:
    run, version, policy, proposal, tools, calls = _fixture(
        GovernanceDecision.REQUIRE_APPROVAL
    )

    plan = plan_governed_tool_consequence(
        run=run,
        agent_version=version,
        proposal=proposal,
        policy=policy,
        tools=tools,
    )

    assert plan.evaluation.effective_decision is GovernanceDecision.REQUIRE_APPROVAL
    assert plan.prepared is None
    assert plan.denied_call is None
    assert calls == []


def test_governed_planner_rejects_policy_identity_drift() -> None:
    run, version, policy, proposal, tools, _ = _fixture(GovernanceDecision.ALLOW)
    object.__setattr__(policy, "id", uuid4())

    try:
        plan_governed_tool_consequence(
            run=run,
            agent_version=version,
            proposal=proposal,
            policy=policy,
            tools=tools,
        )
    except ValueError as exc:
        assert "exact pinned policy identity" in str(exc)
    else:
        raise AssertionError("policy identity drift must fail closed")
