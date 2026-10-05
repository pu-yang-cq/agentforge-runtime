from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentforge.application.approval_review import (
    ApprovalReviewProjection,
    build_pending_approval_review_projection,
)
from agentforge.domain.approvals import ApprovalRequest
from agentforge.domain.enums import ApprovalRequestStatus
from agentforge.domain.governance_decisions import GovernanceIntentV1, PolicyDecision
from agentforge.infrastructure.db.mappers import (
    action_snapshot_from_row,
    external_action_from_row,
    tool_call_from_row,
)
from agentforge.infrastructure.db.models import (
    ActionSnapshotRow,
    ApprovalRequestRow,
    ExternalActionRow,
    GovernanceIntentRow,
    PolicyDecisionRow,
    ToolCallRow,
)


class PostgresApprovalReviewStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def get_pending(self, approval_request_id: UUID) -> ApprovalReviewProjection | None:
        async with self._sessions() as session:
            request_row = await session.get(ApprovalRequestRow, approval_request_id)
            if request_row is None or request_row.status is not ApprovalRequestStatus.PENDING:
                return None

            decision_row = await session.get(PolicyDecisionRow, request_row.policy_decision_id)
            if decision_row is None:
                raise RuntimeError("ApprovalRequest points to missing PolicyDecision")
            intent_row = await session.get(
                GovernanceIntentRow,
                decision_row.governance_intent_id,
            )
            if intent_row is None:
                raise RuntimeError("PolicyDecision points to missing GovernanceIntent")
            call_row = await session.get(ToolCallRow, request_row.tool_call_id)
            if call_row is None:
                raise RuntimeError("ApprovalRequest points to missing ToolCall")

            action_row = None
            snapshot_row = None
            if request_row.external_action_id is not None:
                action_row = await session.get(
                    ExternalActionRow,
                    request_row.external_action_id,
                )
                if action_row is None:
                    raise RuntimeError("ApprovalRequest points to missing ExternalAction")
                snapshot_row = await session.get(
                    ActionSnapshotRow,
                    action_row.action_snapshot_id,
                )
                if snapshot_row is None:
                    raise RuntimeError("ExternalAction points to missing ActionSnapshot")

            request = ApprovalRequest(
                id=request_row.id,
                run_id=request_row.run_id,
                tool_call_id=request_row.tool_call_id,
                external_action_id=request_row.external_action_id,
                policy_decision_id=request_row.policy_decision_id,
                governance_intent_digest=request_row.governance_intent_digest,
                action_snapshot_digest=request_row.action_snapshot_digest,
                requested_by_principal=request_row.requested_by_principal,
                principal_scope=request_row.principal_scope,
                required_approver_role=request_row.required_approver_role,
                separation_of_duties=request_row.separation_of_duties,
                status=request_row.status,
                expires_at=request_row.expires_at,
                created_at=request_row.created_at,
                decided_at=request_row.decided_at,
            )
            intent = GovernanceIntentV1(
                run_id=intent_row.run_id,
                agent_version_id=intent_row.agent_version_id,
                proposal_id=intent_row.proposal_id,
                tool_version_id=intent_row.tool_version_id,
                effect_type=intent_row.effect_type,
                requester_principal_id=intent_row.requester_principal_id,
                requester_principal_type=intent_row.requester_principal_type,
                requester_roles=tuple(intent_row.requester_roles),
                principal_scope=intent_row.principal_scope,
                canonical_json=intent_row.canonical_json,
                digest=intent_row.digest,
                format_version=intent_row.format_version,
            )
            decision = PolicyDecision(
                id=decision_row.id,
                run_id=decision_row.run_id,
                proposal_id=decision_row.proposal_id,
                tool_version_id=decision_row.tool_version_id,
                policy_version_id=decision_row.policy_version_id,
                requester_principal_id=decision_row.requester_principal_id,
                principal_scope=decision_row.principal_scope,
                effective_decision=decision_row.effective_decision,
                matched_rule_id=decision_row.matched_rule_id,
                intent_digest=decision_row.intent_digest,
                created_at=decision_row.created_at,
            )

            return build_pending_approval_review_projection(
                request=request,
                intent=intent,
                decision=decision,
                call=tool_call_from_row(call_row),
                snapshot=(None if snapshot_row is None else action_snapshot_from_row(snapshot_row)),
                action=None if action_row is None else external_action_from_row(action_row),
            )
