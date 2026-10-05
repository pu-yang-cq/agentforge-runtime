from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

from agentforge.domain.actions import canonical_json_v1
from agentforge.domain.enums import (
    GovernanceDecision,
    GovernancePolicyStatus,
    PrincipalType,
    ToolEffectType,
)
from agentforge.domain.governance import (
    GovernanceApprovalRequirement,
    GovernancePolicyRule,
    GovernancePolicyVersion,
    PrincipalContext,
    normalize_policy_rules,
)
from agentforge.domain.models import ToolBinding

GOVERNANCE_INTENT_FORMAT_VERSION = 1

_DECISION_ORDER = {
    GovernanceDecision.DENY: 0,
    GovernanceDecision.REQUIRE_APPROVAL: 1,
    GovernanceDecision.ALLOW: 2,
}


@dataclass(frozen=True, slots=True)
class GovernanceIntentV1:
    run_id: UUID
    agent_version_id: UUID
    proposal_id: UUID
    tool_version_id: UUID
    effect_type: ToolEffectType
    requester_principal_id: str
    requester_principal_type: PrincipalType
    requester_roles: tuple[str, ...]
    principal_scope: str
    canonical_json: str
    digest: str
    format_version: int = GOVERNANCE_INTENT_FORMAT_VERSION

    @classmethod
    def create(
        cls,
        *,
        run_id: UUID,
        agent_version_id: UUID,
        proposal_id: UUID,
        binding: ToolBinding,
        arguments: dict[str, Any],
        principal: PrincipalContext,
    ) -> GovernanceIntentV1:
        payload = {
            "agent_version_id": str(agent_version_id),
            "arguments": arguments,
            "effect_type": binding.effect_type.value,
            "format_version": GOVERNANCE_INTENT_FORMAT_VERSION,
            "principal_scope": principal.principal_scope,
            "proposal_id": str(proposal_id),
            "requester": {
                "principal_id": principal.principal_id,
                "principal_type": principal.principal_type.value,
                "roles": list(principal.roles),
            },
            "run_id": str(run_id),
            "tool_version_id": str(binding.tool_version_id),
        }
        canonical = canonical_json_v1(payload)
        return cls(
            run_id=run_id,
            agent_version_id=agent_version_id,
            proposal_id=proposal_id,
            tool_version_id=binding.tool_version_id,
            effect_type=binding.effect_type,
            requester_principal_id=principal.principal_id,
            requester_principal_type=principal.principal_type,
            requester_roles=principal.roles,
            principal_scope=principal.principal_scope,
            canonical_json=canonical.decode("utf-8"),
            digest=sha256(canonical).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class PolicyEvaluation:
    raw_decision: GovernanceDecision
    effective_decision: GovernanceDecision
    matched_rule_id: str | None
    approval: GovernanceApprovalRequirement | None = None


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    id: UUID
    run_id: UUID
    proposal_id: UUID
    tool_version_id: UUID
    policy_version_id: UUID
    requester_principal_id: str
    principal_scope: str
    effective_decision: GovernanceDecision
    matched_rule_id: str | None
    intent_digest: str
    created_at: datetime


def _matches(
    rule: GovernancePolicyRule,
    *,
    principal: PrincipalContext,
    agent_version_id: UUID,
    binding: ToolBinding,
) -> bool:
    if rule.principal_roles_any and not set(rule.principal_roles_any).intersection(principal.roles):
        return False
    if rule.agent_version_ids and agent_version_id not in rule.agent_version_ids:
        return False
    if rule.tool_version_ids and binding.tool_version_id not in rule.tool_version_ids:
        return False
    if rule.effect_types and binding.effect_type not in rule.effect_types:
        return False
    return not rule.principal_scopes or principal.principal_scope in rule.principal_scopes


def _effective_decision(
    raw_decision: GovernanceDecision,
    *,
    binding: ToolBinding,
) -> GovernanceDecision:
    if raw_decision is GovernanceDecision.DENY:
        return GovernanceDecision.DENY

    if binding.effect_type is ToolEffectType.READ:
        if binding.approval_required or raw_decision is GovernanceDecision.REQUIRE_APPROVAL:
            return GovernanceDecision.REQUIRE_APPROVAL
        return GovernanceDecision.ALLOW

    if binding.effect_type in {
        ToolEffectType.WRITE,
        ToolEffectType.EXTERNAL_SIDE_EFFECT,
    }:
        if binding.approval_required or raw_decision is GovernanceDecision.REQUIRE_APPROVAL:
            return GovernanceDecision.REQUIRE_APPROVAL
        if binding.allow_no_approval_execution:
            return GovernanceDecision.ALLOW
        return GovernanceDecision.REQUIRE_APPROVAL

    if binding.effect_type is ToolEffectType.DESTRUCTIVE:
        return GovernanceDecision.REQUIRE_APPROVAL

    return GovernanceDecision.DENY


def evaluate_policy(
    policy: GovernancePolicyVersion,
    *,
    principal: PrincipalContext,
    agent_version_id: UUID,
    binding: ToolBinding,
) -> PolicyEvaluation:
    if policy.status not in {
        GovernancePolicyStatus.PUBLISHED,
        GovernancePolicyStatus.RETIRED,
    }:
        return PolicyEvaluation(
            raw_decision=GovernanceDecision.DENY,
            effective_decision=GovernanceDecision.DENY,
            matched_rule_id=None,
        )

    try:
        rules = normalize_policy_rules(policy.rules)
        matching = [
            rule
            for rule in rules
            if _matches(
                rule,
                principal=principal,
                agent_version_id=agent_version_id,
                binding=binding,
            )
        ]
        if not matching:
            return PolicyEvaluation(
                raw_decision=GovernanceDecision.DENY,
                effective_decision=GovernanceDecision.DENY,
                matched_rule_id=None,
            )

        selected = min(
            matching,
            key=lambda rule: (
                -rule.priority,
                _DECISION_ORDER[rule.decision],
                rule.rule_id,
            ),
        )
        effective = _effective_decision(selected.decision, binding=binding)
        if effective is GovernanceDecision.REQUIRE_APPROVAL and selected.approval is None:
            return PolicyEvaluation(
                raw_decision=selected.decision,
                effective_decision=GovernanceDecision.DENY,
                matched_rule_id=selected.rule_id,
            )
        return PolicyEvaluation(
            raw_decision=selected.decision,
            effective_decision=effective,
            matched_rule_id=selected.rule_id,
            approval=(
                selected.approval if effective is GovernanceDecision.REQUIRE_APPROVAL else None
            ),
        )
    except AttributeError, KeyError, TypeError, ValueError:
        return PolicyEvaluation(
            raw_decision=GovernanceDecision.DENY,
            effective_decision=GovernanceDecision.DENY,
            matched_rule_id=None,
        )
