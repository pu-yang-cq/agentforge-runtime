from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from agentforge.domain.actions import ActionSnapshot, ExternalAction, canonical_json_v1
from agentforge.domain.approvals import ApprovalRequest
from agentforge.domain.enums import (
    ApprovalRequestStatus,
    ExternalActionStatus,
    GovernanceDecision,
    ToolCallStatus,
    ToolEffectType,
)
from agentforge.domain.governance_decisions import GovernanceIntentV1, PolicyDecision
from agentforge.domain.models import ToolCall


@dataclass(frozen=True, slots=True)
class ApprovalReviewProjection:
    approval_request_id: UUID
    run_id: UUID
    tool_call_id: UUID
    external_action_id: UUID | None
    policy_decision_id: UUID
    policy_version_id: UUID
    matched_rule_id: str | None
    governance_intent_digest: str
    action_snapshot_digest: str | None
    requested_by_principal: str
    principal_scope: str
    required_approver_role: str
    separation_of_duties: bool
    status: ApprovalRequestStatus
    expires_at: datetime
    created_at: datetime
    tool_name: str
    tool_version_id: UUID
    effect_type: ToolEffectType
    arguments_canonical_json: str
    operation_id: UUID | None


def build_pending_approval_review_projection(
    *,
    request: ApprovalRequest,
    intent: GovernanceIntentV1,
    decision: PolicyDecision,
    call: ToolCall,
    snapshot: ActionSnapshot | None,
    action: ExternalAction | None,
) -> ApprovalReviewProjection:
    if request.status is not ApprovalRequestStatus.PENDING:
        raise ValueError("approval review projection requires PENDING request")
    if decision.effective_decision is not GovernanceDecision.REQUIRE_APPROVAL:
        raise ValueError("approval review projection requires REQUIRE_APPROVAL decision")
    if call.status is not ToolCallStatus.AWAITING_APPROVAL:
        raise ValueError("approval review projection requires AWAITING_APPROVAL ToolCall")
    tool_version_id = call.tool_version_id
    if tool_version_id is None:
        raise ValueError("approval review ToolCall must bind a ToolVersion")

    if not (
        request.run_id == intent.run_id == decision.run_id == call.run_id
        and request.tool_call_id == call.id
        and request.policy_decision_id == decision.id
        and intent.proposal_id == decision.proposal_id == call.proposal_id
        and intent.tool_version_id == decision.tool_version_id == tool_version_id
    ):
        raise ValueError("approval review durable identity mismatch")
    if not (
        request.governance_intent_digest == intent.digest == decision.intent_digest
    ):
        raise ValueError("approval review GovernanceIntent digest mismatch")
    if (
        request.requested_by_principal != intent.requester_principal_id
        or decision.requester_principal_id != intent.requester_principal_id
        or request.principal_scope != intent.principal_scope
        or decision.principal_scope != intent.principal_scope
    ):
        raise ValueError("approval review requester authority mismatch")

    operation_id: UUID | None = None
    if request.external_action_id is None:
        if snapshot is not None or action is not None:
            raise ValueError("READ approval review cannot include side-effect identity")
        if request.action_snapshot_digest is not None:
            raise ValueError("READ approval review cannot bind ActionSnapshot digest")
        if intent.effect_type is not ToolEffectType.READ:
            raise ValueError("approval review without ExternalAction must be READ")
    else:
        if snapshot is None or action is None:
            raise ValueError("side-effect approval review requires action and snapshot")
        if action.status is not ExternalActionStatus.AWAITING_APPROVAL:
            raise ValueError(
                "side-effect approval review requires AWAITING_APPROVAL ExternalAction"
            )
        if action.current_attempt_id is not None:
            raise ValueError("pending approval ExternalAction cannot have active attempt")
        if not (
            request.external_action_id == action.id
            and action.run_id == request.run_id
            and action.tool_call_id == call.id
            and action.action_snapshot_id == snapshot.id
        ):
            raise ValueError("approval review ExternalAction binding mismatch")
        if request.action_snapshot_digest != snapshot.digest:
            raise ValueError("approval review ActionSnapshot digest mismatch")
        if not (
            snapshot.tool_version_id == tool_version_id == intent.tool_version_id
            and snapshot.effect_type is intent.effect_type
            and snapshot.arguments == call.arguments
            and snapshot.operation_id == action.operation_id
        ):
            raise ValueError("approval review ActionSnapshot identity mismatch")
        operation_id = action.operation_id

    return ApprovalReviewProjection(
        approval_request_id=request.id,
        run_id=request.run_id,
        tool_call_id=request.tool_call_id,
        external_action_id=request.external_action_id,
        policy_decision_id=request.policy_decision_id,
        policy_version_id=decision.policy_version_id,
        matched_rule_id=decision.matched_rule_id,
        governance_intent_digest=request.governance_intent_digest,
        action_snapshot_digest=request.action_snapshot_digest,
        requested_by_principal=request.requested_by_principal,
        principal_scope=request.principal_scope,
        required_approver_role=request.required_approver_role,
        separation_of_duties=request.separation_of_duties,
        status=request.status,
        expires_at=request.expires_at,
        created_at=request.created_at,
        tool_name=call.tool_name,
        tool_version_id=tool_version_id,
        effect_type=intent.effect_type,
        arguments_canonical_json=canonical_json_v1(call.arguments).decode("utf-8"),
        operation_id=operation_id,
    )
