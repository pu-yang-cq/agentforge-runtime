from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from agentforge.application.governed_consequence import plan_governed_tool_consequence
from agentforge.application.run_manager import ExecutionJournal, RunManager
from agentforge.domain.actions import ExternalAction
from agentforge.domain.approvals import ApprovalRequest
from agentforge.domain.enums import (
    ApprovalRequestStatus,
    ExternalActionStatus,
    GovernanceDecision,
    GovernanceMode,
    GovernancePolicyStatus,
    PrincipalType,
    RunStatus,
    ToolCallStatus,
    ToolEffectType,
)
from agentforge.domain.governance import (
    GovernanceApprovalRequirement,
    GovernancePolicyRule,
    GovernancePolicyVersion,
)
from agentforge.domain.models import (
    AgentVersion,
    Run,
    RunState,
    ToolBinding,
    ToolCall,
    ToolProposal,
)
from agentforge.runtime.fake_model import ScriptedFakeModel, ToolStep
from agentforge.runtime.native_runner import NativeRunner
from agentforge.runtime.tool_coordinator import ToolCoordinator
from agentforge.runtime.tools import InMemoryToolRegistry, SideEffectFunctionTool

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]


def _proposal(run_id):
    return ToolProposal.create(
        run_id=run_id,
        model_invocation_id=uuid4(),
        tool_name="lookup",
        arguments={"q": "hello"},
    )


def test_pending_domain_states_enter_without_resume_semantics() -> None:
    run = Run(
        id=uuid4(),
        agent_version_id=uuid4(),
        input_text="approval",
    )
    run.queue()
    run.start()
    run.owner_worker_id = "worker-c"
    run.lease_expires_at = NOW + timedelta(seconds=30)

    proposal = _proposal(run.id)
    call = ToolCall.from_proposal(proposal, tool_version_id=uuid4())
    call.await_approval()
    action = ExternalAction.awaiting_approval(
        run_id=run.id,
        tool_call_id=call.id,
        action_snapshot_id=uuid4(),
        operation_id=uuid4(),
    )
    run.wait_for_approval()

    assert run.status is RunStatus.WAITING_APPROVAL
    assert run.owner_worker_id is None
    assert run.lease_expires_at is None
    assert call.status is ToolCallStatus.AWAITING_APPROVAL
    assert action.status is ExternalActionStatus.AWAITING_APPROVAL
    assert action.current_attempt_id is None

    assert not hasattr(Run, "resume_after_approval")
    assert not hasattr(ApprovalRequest, "approve")
    assert not hasattr(ApprovalRequest, "deny")


def test_read_approval_request_binds_governance_intent_only() -> None:
    request = ApprovalRequest(
        id=uuid4(),
        run_id=uuid4(),
        tool_call_id=uuid4(),
        external_action_id=None,
        policy_decision_id=uuid4(),
        governance_intent_digest="a" * 64,
        action_snapshot_digest=None,
        requested_by_principal="  requester ",
        principal_scope=" tenant-a ",
        required_approver_role=" approver ",
        separation_of_duties=True,
        status=ApprovalRequestStatus.PENDING,
        expires_at=NOW + timedelta(minutes=10),
        created_at=NOW,
    )

    assert request.requested_by_principal == "requester"
    assert request.principal_scope == "tenant-a"
    assert request.required_approver_role == "approver"
    assert request.is_side_effect is False
    assert request.decided_at is None


def test_side_effect_approval_request_requires_both_action_bindings() -> None:
    request = ApprovalRequest(
        id=uuid4(),
        run_id=uuid4(),
        tool_call_id=uuid4(),
        external_action_id=uuid4(),
        policy_decision_id=uuid4(),
        governance_intent_digest="a" * 64,
        action_snapshot_digest="b" * 64,
        requested_by_principal="requester",
        principal_scope="tenant-a",
        required_approver_role="approver",
        separation_of_duties=False,
        status=ApprovalRequestStatus.PENDING,
        expires_at=NOW + timedelta(minutes=5),
        created_at=NOW,
    )
    assert request.is_side_effect is True

    with pytest.raises(ValueError, match="both be set or both be null"):
        ApprovalRequest(
            id=uuid4(),
            run_id=uuid4(),
            tool_call_id=uuid4(),
            external_action_id=uuid4(),
            policy_decision_id=uuid4(),
            governance_intent_digest="a" * 64,
            action_snapshot_digest=None,
            requested_by_principal="requester",
            principal_scope="tenant-a",
            required_approver_role="approver",
            separation_of_duties=False,
            status=ApprovalRequestStatus.PENDING,
            expires_at=NOW + timedelta(minutes=5),
            created_at=NOW,
        )


def test_approval_request_rejects_invalid_digest_expiry_and_decided_shape() -> None:
    base = dict(
        id=uuid4(),
        run_id=uuid4(),
        tool_call_id=uuid4(),
        external_action_id=None,
        policy_decision_id=uuid4(),
        governance_intent_digest="a" * 64,
        action_snapshot_digest=None,
        requested_by_principal="requester",
        principal_scope="tenant-a",
        required_approver_role="approver",
        separation_of_duties=True,
        status=ApprovalRequestStatus.PENDING,
        expires_at=NOW + timedelta(minutes=5),
        created_at=NOW,
    )

    with pytest.raises(ValueError, match="SHA-256"):
        ApprovalRequest(**{**base, "governance_intent_digest": "A" * 64})

    with pytest.raises(ValueError, match="later than"):
        ApprovalRequest(**{**base, "expires_at": NOW})

    with pytest.raises(ValueError, match="cannot have decided_at"):
        ApprovalRequest(**{**base, "decided_at": NOW + timedelta(seconds=1)})

    with pytest.raises(ValueError, match="requires decided_at"):
        ApprovalRequest(**{**base, "status": ApprovalRequestStatus.APPROVED})


def test_0019_approval_intent_migration_extends_existing_progression_guards() -> None:
    migration = (ROOT / "migrations" / "versions" / "0019_approval_intent.py").read_text()

    assert 'revision: str = "0019_approval_intent"' in migration
    assert 'down_revision: str | None = "0018_governance_decision"' in migration
    assert "ALTER TYPE run_status ADD VALUE IF NOT EXISTS 'WAITING_APPROVAL'" in migration
    assert "ALTER TYPE tool_call_status ADD VALUE IF NOT EXISTS 'AWAITING_APPROVAL'" in migration
    assert (
        "ALTER TYPE external_action_status ADD VALUE IF NOT EXISTS 'AWAITING_APPROVAL'" in migration
    )
    assert "uq_tool_calls_one_active_per_run" in migration
    assert "uq_external_actions_one_nonterminal_per_run" in migration
    assert "uq_approval_requests_one_pending_per_run" in migration
    assert "ck_approval_requests_action_binding_shape" in migration
    assert "ck_approval_requests_status_decided_shape" in migration
    assert "CREATE" not in migration or "ApprovalDecision" not in migration
    assert "expire_due_approvals" not in migration


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "effect_type",
    [ToolEffectType.EXTERNAL_SIDE_EFFECT, ToolEffectType.DESTRUCTIVE],
)
async def test_run_manager_side_effect_require_approval_enters_waiting_without_io(
    effect_type: ToolEffectType,
) -> None:
    tool_version_id = uuid4()
    policy_id = uuid4()
    agent_version_id = uuid4()
    calls: list[str] = []

    registry = InMemoryToolRegistry(
        [
            SideEffectFunctionTool(
                version_id=tool_version_id,
                name="effect",
                description="effect",
                input_schema={"type": "object"},
                func=lambda invocation: calls.append(str(invocation.operation_id)) or {"ok": True},
            )
        ]
    )
    binding = ToolBinding(
        tool_version_id=tool_version_id,
        name="effect",
        effect_type=effect_type,
        credential_ref="credential://effect",
    )
    version = AgentVersion(
        id=agent_version_id,
        agent_id=uuid4(),
        version_number=1,
        instructions="approval",
        tool_bindings=(binding,),
        governance_mode=GovernanceMode.GOVERNED,
        policy_version_id=policy_id,
    )
    run = Run(
        id=uuid4(),
        agent_version_id=version.id,
        input_text="needs approval",
        policy_version_id=policy_id,
        requester_principal_id="requester",
        requester_principal_type=PrincipalType.USER,
        requester_roles=("operator",),
        requester_scope="tenant-c",
        requester_authn_source="test-oidc",
    )
    run.queue()
    policy = GovernancePolicyVersion(
        id=policy_id,
        policy_key="c-side-effect",
        version_number=1,
        status=GovernancePolicyStatus.PUBLISHED,
        rules=(
            GovernancePolicyRule(
                rule_id="require",
                priority=100,
                decision=GovernanceDecision.REQUIRE_APPROVAL,
                approval=GovernanceApprovalRequirement("approver", True, 600),
            ),
        ),
        created_at=NOW,
        published_at=NOW,
    )
    manager = RunManager(
        NativeRunner(
            ScriptedFakeModel([ToolStep("effect", {"ticket": "exact"})]),
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

    assert result is None
    assert run.status is RunStatus.WAITING_APPROVAL
    assert calls == []
    assert len(journal.tool_calls) == 1
    assert journal.tool_calls[0].status is ToolCallStatus.AWAITING_APPROVAL
    assert len(journal.action_snapshots) == 1
    assert len(journal.external_actions) == 1
    assert journal.external_actions[0].status is ExternalActionStatus.AWAITING_APPROVAL
    assert journal.external_actions[0].current_attempt_id is None
    assert len(journal.approval_requests) == 1
    assert journal.approval_requests[0].external_action_id == journal.external_actions[0].id
    assert journal.approval_requests[0].action_snapshot_digest == journal.action_snapshots[0].digest
    assert journal.tool_attempts == []


def test_capability_derived_approval_without_metadata_fails_closed_to_deny_zero_io() -> None:
    tool_version_id = uuid4()
    policy_id = uuid4()
    binding = ToolBinding(
        tool_version_id=tool_version_id,
        name="effect",
        effect_type=ToolEffectType.EXTERNAL_SIDE_EFFECT,
    )
    version = AgentVersion(
        id=uuid4(),
        agent_id=uuid4(),
        version_number=1,
        instructions="approval metadata guard",
        tool_bindings=(binding,),
        governance_mode=GovernanceMode.GOVERNED,
        policy_version_id=policy_id,
    )
    run = Run(
        id=uuid4(),
        agent_version_id=version.id,
        input_text="guard",
        policy_version_id=policy_id,
        requester_principal_id="requester",
        requester_principal_type=PrincipalType.USER,
        requester_roles=("operator",),
        requester_scope="tenant-c",
        requester_authn_source="test-oidc",
    )
    policy = GovernancePolicyVersion(
        id=policy_id,
        policy_key="c-derived-approval",
        version_number=1,
        status=GovernancePolicyStatus.PUBLISHED,
        rules=(
            GovernancePolicyRule(
                rule_id="raw-allow",
                priority=100,
                decision=GovernanceDecision.ALLOW,
            ),
        ),
        created_at=NOW,
        published_at=NOW,
    )
    proposal = ToolProposal.create(
        run_id=run.id,
        model_invocation_id=uuid4(),
        tool_name="effect",
        arguments={"ticket": "guard"},
    )
    calls: list[str] = []
    registry = InMemoryToolRegistry(
        [
            SideEffectFunctionTool(
                version_id=tool_version_id,
                name="effect",
                description="effect",
                input_schema={"type": "object"},
                func=lambda invocation: calls.append(str(invocation.operation_id)) or {"ok": True},
            )
        ]
    )

    plan = plan_governed_tool_consequence(
        run=run,
        agent_version=version,
        proposal=proposal,
        policy=policy,
        tools=ToolCoordinator(registry),
    )

    assert plan.evaluation.raw_decision is GovernanceDecision.ALLOW
    assert plan.evaluation.effective_decision is GovernanceDecision.DENY
    assert plan.evaluation.approval is None
    assert plan.denied_call is not None
    assert plan.pending_call is None
    assert plan.prepared is None
    assert calls == []


def test_capability_derived_approval_uses_exact_allow_fallback_metadata() -> None:
    tool_version_id = uuid4()
    policy_id = uuid4()
    approval = GovernanceApprovalRequirement("risk-approver", True, 900)
    binding = ToolBinding(
        tool_version_id=tool_version_id,
        name="destroy",
        effect_type=ToolEffectType.DESTRUCTIVE,
        credential_ref="credential://destructive",
    )
    version = AgentVersion(
        id=uuid4(),
        agent_id=uuid4(),
        version_number=1,
        instructions="fallback approval",
        tool_bindings=(binding,),
        governance_mode=GovernanceMode.GOVERNED,
        policy_version_id=policy_id,
    )
    run = Run(
        id=uuid4(),
        agent_version_id=version.id,
        input_text="fallback",
        policy_version_id=policy_id,
        requester_principal_id="requester",
        requester_principal_type=PrincipalType.USER,
        requester_roles=("operator",),
        requester_scope="tenant-c",
        requester_authn_source="test-oidc",
    )
    policy = GovernancePolicyVersion(
        id=policy_id,
        policy_key="c-fallback",
        version_number=1,
        status=GovernancePolicyStatus.PUBLISHED,
        rules=(
            GovernancePolicyRule(
                rule_id="raw-allow-with-fallback",
                priority=100,
                decision=GovernanceDecision.ALLOW,
                approval=approval,
            ),
        ),
        created_at=NOW,
        published_at=NOW,
    )
    proposal = ToolProposal.create(
        run_id=run.id,
        model_invocation_id=uuid4(),
        tool_name="destroy",
        arguments={"resource": "exact"},
    )
    calls: list[str] = []
    registry = InMemoryToolRegistry(
        [
            SideEffectFunctionTool(
                version_id=tool_version_id,
                name="destroy",
                description="destroy",
                input_schema={"type": "object"},
                func=lambda invocation: calls.append(str(invocation.operation_id)) or {"ok": True},
            )
        ]
    )

    plan = plan_governed_tool_consequence(
        run=run,
        agent_version=version,
        proposal=proposal,
        policy=policy,
        tools=ToolCoordinator(registry),
    )

    assert plan.evaluation.raw_decision is GovernanceDecision.ALLOW
    assert plan.evaluation.effective_decision is GovernanceDecision.REQUIRE_APPROVAL
    assert plan.evaluation.approval == approval
    assert plan.pending_call is not None
    assert plan.pending_snapshot is not None
    assert plan.pending_action is not None
    assert plan.pending_snapshot.effect_type is ToolEffectType.DESTRUCTIVE
    assert plan.pending_action.operation_id == plan.pending_snapshot.operation_id
    assert calls == []
