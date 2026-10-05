from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from agentforge.domain.actions import ExternalAction
from agentforge.domain.approvals import ApprovalRequest
from agentforge.domain.enums import (
    ApprovalRequestStatus,
    ExternalActionStatus,
    RunStatus,
    ToolCallStatus,
)
from agentforge.domain.models import Run, ToolCall, ToolProposal

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
        "ALTER TYPE external_action_status ADD VALUE IF NOT EXISTS 'AWAITING_APPROVAL'"
        in migration
    )
    assert "uq_tool_calls_one_active_per_run" in migration
    assert "uq_external_actions_one_nonterminal_per_run" in migration
    assert "uq_approval_requests_one_pending_per_run" in migration
    assert "ck_approval_requests_action_binding_shape" in migration
    assert "ck_approval_requests_status_decided_shape" in migration
    assert "CREATE" not in migration or "ApprovalDecision" not in migration
    assert "expire_due_approvals" not in migration
