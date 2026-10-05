from datetime import UTC, datetime
from uuid import uuid4

import pytest

from agentforge.application.errors import RunExecutionFailedError
from agentforge.application.governed_consequence import plan_governed_tool_consequence
from agentforge.application.run_manager import ExecutionJournal, RunManager
from agentforge.application.worker import CoreWorker
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
from agentforge.domain.models import AgentVersion, Run, RunState, ToolBinding, ToolProposal
from agentforge.runtime.fake_model import FinalStep, ScriptedFakeModel, ToolStep
from agentforge.runtime.native_runner import NativeRunner
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



def _runtime_fixture(decision: GovernanceDecision):
    tool_version_id = uuid4()
    policy_id = uuid4()
    agent_version = AgentVersion(
        id=uuid4(),
        agent_id=uuid4(),
        version_number=1,
        instructions="governed runtime",
        tool_bindings=(
            ToolBinding(
                tool_version_id=tool_version_id,
                name="lookup",
                effect_type=ToolEffectType.READ,
            ),
        ),
        governance_mode=GovernanceMode.GOVERNED,
        policy_version_id=policy_id,
    )
    run = Run(
        id=uuid4(),
        agent_version_id=agent_version.id,
        input_text="governed runtime request",
        policy_version_id=policy_id,
        requester_principal_id="user-runtime",
        requester_principal_type=PrincipalType.USER,
        requester_roles=("operator",),
        requester_scope="tenant-runtime",
        requester_authn_source="test-oidc",
    )
    run.queue()
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
        policy_key=f"runtime-{decision.value.lower()}",
        version_number=1,
        status=GovernancePolicyStatus.PUBLISHED,
        rules=(
            GovernancePolicyRule(
                rule_id="runtime-rule",
                priority=100,
                decision=decision,
                approval=approval,
            ),
        ),
        created_at=NOW,
        published_at=NOW,
    )
    calls: list[str] = []
    registry = InMemoryToolRegistry(
        [
            FunctionTool(
                version_id=tool_version_id,
                name="lookup",
                description="lookup",
                input_schema={"type": "object"},
                func=lambda q: calls.append(q) or {"q": q},
            )
        ]
    )
    return run, agent_version, policy, registry, calls


@pytest.mark.asyncio
async def test_run_manager_governed_read_allow_uses_governed_recorder_before_io() -> None:
    run, version, policy, registry, calls = _runtime_fixture(GovernanceDecision.ALLOW)
    manager = RunManager(
        NativeRunner(
            ScriptedFakeModel(
                [
                    ToolStep("lookup", {"q": "hello"}),
                    FinalStep("done"),
                ]
            ),
            registry,
        ),
        ToolCoordinator(registry),
    )
    journal = ExecutionJournal()

    result = await manager.execute(
        run=run,
        run_state=RunState(run.id),
        agent_version=version,
        recorder=journal,
        governance_policy=policy,
    )

    assert result == "done"
    assert calls == ["hello"]
    assert len(journal.governance_intents) == 1
    assert len(journal.governance_evaluations) == 1
    assert (
        journal.governance_evaluations[0].effective_decision
        is GovernanceDecision.ALLOW
    )
    assert len(journal.tool_attempts) == 1
    assert journal.tool_calls[0].status is ToolCallStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_run_manager_governed_deny_records_bound_denial_and_zero_io() -> None:
    run, version, policy, registry, calls = _runtime_fixture(GovernanceDecision.DENY)
    manager = RunManager(
        NativeRunner(
            ScriptedFakeModel([ToolStep("lookup", {"q": "blocked"})]),
            registry,
        ),
        ToolCoordinator(registry),
    )
    journal = ExecutionJournal()

    with pytest.raises(RunExecutionFailedError):
        await manager.execute(
            run=run,
            run_state=RunState(run.id),
            agent_version=version,
            recorder=journal,
            governance_policy=policy,
        )

    assert calls == []
    assert len(journal.governance_intents) == 1
    assert journal.governance_evaluations[0].effective_decision is GovernanceDecision.DENY
    assert len(journal.tool_calls) == 1
    assert journal.tool_calls[0].status is ToolCallStatus.DENIED
    assert journal.tool_calls[0].tool_version_id == version.tool_bindings[0].tool_version_id
    assert journal.tool_attempts == []


@pytest.mark.asyncio
async def test_run_manager_require_approval_stops_at_stage33_c_boundary() -> None:
    run, version, policy, registry, calls = _runtime_fixture(
        GovernanceDecision.REQUIRE_APPROVAL
    )
    manager = RunManager(
        NativeRunner(
            ScriptedFakeModel([ToolStep("lookup", {"q": "needs approval"})]),
            registry,
        ),
        ToolCoordinator(registry),
    )
    journal = ExecutionJournal()

    with pytest.raises(RuntimeError, match="belongs to Stage 3.3-C"):
        await manager.execute(
            run=run,
            run_state=RunState(run.id),
            agent_version=version,
            recorder=journal,
            governance_policy=policy,
        )

    assert calls == []
    assert journal.governance_intents == []
    assert journal.tool_calls == []
    assert journal.tool_attempts == []


class _WorkerRuntimeStore:
    def __init__(self, run: Run, agent_version: AgentVersion) -> None:
        self.run = run
        self.agent_version = agent_version
        self.claimed = False

    async def claim_next_run(self, *, worker_id: str, lease_seconds: int):
        if self.claimed:
            return None
        self.claimed = True
        return self.run

    async def renew_lease(self, **kwargs):
        return True

    async def load_agent_version(self, agent_version_id):
        assert agent_version_id == self.agent_version.id
        return self.agent_version

    async def load_run_state(self, run_id):
        return RunState(run_id)


class _ExactPolicyStore:
    def __init__(self, policy: GovernancePolicyVersion) -> None:
        self.policy = policy
        self.requested_ids = []

    async def get(self, policy_version_id):
        self.requested_ids.append(policy_version_id)
        return self.policy if policy_version_id == self.policy.id else None


@pytest.mark.asyncio
async def test_worker_loads_exact_pinned_policy_only_for_governed_run() -> None:
    run, version, policy, registry, _ = _runtime_fixture(GovernanceDecision.ALLOW)
    journal = ExecutionJournal()
    policy_store = _ExactPolicyStore(policy)
    worker = CoreWorker(
        runtime_store=_WorkerRuntimeStore(run, version),
        recorder_factory=lambda **_: journal,
        tool_registry=registry,
        model_factory=lambda _: ScriptedFakeModel([FinalStep("worker done")]),
        worker_id="governed-worker",
        lease_seconds=30,
        governance_policy_store=policy_store,
    )

    assert await worker.run_once() is True
    assert policy_store.requested_ids == [policy.id]
    assert run.status.value == "COMPLETED"
