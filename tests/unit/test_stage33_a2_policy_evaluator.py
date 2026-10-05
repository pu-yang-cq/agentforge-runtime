from datetime import UTC, datetime
from itertools import permutations
from uuid import uuid4

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
)
from agentforge.domain.governance_decisions import evaluate_policy
from agentforge.domain.models import ToolBinding

NOW = datetime(2026, 10, 5, tzinfo=UTC)


def _principal() -> PrincipalContext:
    return PrincipalContext(
        principal_id="user-1",
        principal_type=PrincipalType.USER,
        roles=("operator", "runtime:run:create"),
        principal_scope="tenant-a",
        authn_source="test",
    )


def _policy(
    rules: tuple[GovernancePolicyRule, ...],
    *,
    status: GovernancePolicyStatus = GovernancePolicyStatus.PUBLISHED,
) -> GovernancePolicyVersion:
    return GovernancePolicyVersion(
        id=uuid4(),
        policy_key="a2-policy",
        version_number=1,
        status=status,
        rules=rules,
        created_at=NOW,
        published_at=None if status is GovernancePolicyStatus.DRAFT else NOW,
        retired_at=NOW if status is GovernancePolicyStatus.RETIRED else None,
    )


def test_policy_selection_is_deterministic_by_priority_decision_and_rule_id() -> None:
    principal = _principal()
    agent_version_id = uuid4()
    tool_version_id = uuid4()
    binding = ToolBinding(
        tool_version_id=tool_version_id,
        name="read",
        effect_type=ToolEffectType.READ,
    )
    approval = GovernanceApprovalRequirement("approver", True, 600)
    rules = (
        GovernancePolicyRule(
            rule_id="z-allow",
            priority=50,
            decision=GovernanceDecision.ALLOW,
        ),
        GovernancePolicyRule(
            rule_id="m-require",
            priority=50,
            decision=GovernanceDecision.REQUIRE_APPROVAL,
            approval=approval,
        ),
        GovernancePolicyRule(
            rule_id="z-deny",
            priority=50,
            decision=GovernanceDecision.DENY,
        ),
        GovernancePolicyRule(
            rule_id="a-deny",
            priority=50,
            decision=GovernanceDecision.DENY,
        ),
    )

    results = {
        (
            evaluation.raw_decision,
            evaluation.effective_decision,
            evaluation.matched_rule_id,
        )
        for order in permutations(rules)
        for evaluation in (
            evaluate_policy(
                _policy(tuple(order)),
                principal=principal,
                agent_version_id=agent_version_id,
                binding=binding,
            ),
        )
    }

    assert results == {
        (
            GovernanceDecision.DENY,
            GovernanceDecision.DENY,
            "a-deny",
        )
    }


def test_higher_priority_precedes_more_restrictive_lower_priority_rule() -> None:
    principal = _principal()
    agent_version_id = uuid4()
    binding = ToolBinding(
        tool_version_id=uuid4(),
        name="read",
        effect_type=ToolEffectType.READ,
    )
    policy = _policy(
        (
            GovernancePolicyRule(
                rule_id="lower-deny",
                priority=10,
                decision=GovernanceDecision.DENY,
            ),
            GovernancePolicyRule(
                rule_id="higher-allow",
                priority=20,
                decision=GovernanceDecision.ALLOW,
            ),
        )
    )

    evaluation = evaluate_policy(
        policy,
        principal=principal,
        agent_version_id=agent_version_id,
        binding=binding,
    )

    assert evaluation.raw_decision is GovernanceDecision.ALLOW
    assert evaluation.effective_decision is GovernanceDecision.ALLOW
    assert evaluation.matched_rule_id == "higher-allow"


def test_policy_match_dimensions_and_no_match_fail_closed() -> None:
    principal = _principal()
    agent_version_id = uuid4()
    tool_version_id = uuid4()
    binding = ToolBinding(
        tool_version_id=tool_version_id,
        name="read",
        effect_type=ToolEffectType.READ,
    )
    matching = GovernancePolicyRule(
        rule_id="exact",
        priority=100,
        principal_roles_any=("operator",),
        agent_version_ids=(agent_version_id,),
        tool_version_ids=(tool_version_id,),
        effect_types=(ToolEffectType.READ,),
        principal_scopes=("tenant-a",),
        decision=GovernanceDecision.ALLOW,
    )
    mismatched = GovernancePolicyRule(
        rule_id="wrong-scope",
        priority=200,
        principal_scopes=("tenant-b",),
        decision=GovernanceDecision.DENY,
    )

    evaluation = evaluate_policy(
        _policy((mismatched, matching)),
        principal=principal,
        agent_version_id=agent_version_id,
        binding=binding,
    )
    assert evaluation.effective_decision is GovernanceDecision.ALLOW
    assert evaluation.matched_rule_id == "exact"

    no_match = evaluate_policy(
        _policy((mismatched,)),
        principal=principal,
        agent_version_id=agent_version_id,
        binding=binding,
    )
    assert no_match.raw_decision is GovernanceDecision.DENY
    assert no_match.effective_decision is GovernanceDecision.DENY
    assert no_match.matched_rule_id is None


def test_capability_envelope_never_broadens_tool_binding() -> None:
    principal = _principal()
    agent_version_id = uuid4()
    approval = GovernanceApprovalRequirement("approver", True, 600)
    allow = _policy(
        (
            GovernancePolicyRule(
                rule_id="allow",
                priority=1,
                decision=GovernanceDecision.ALLOW,
            ),
        )
    )
    allow_with_fallback = _policy(
        (
            GovernancePolicyRule(
                rule_id="allow-with-fallback",
                priority=1,
                decision=GovernanceDecision.ALLOW,
                approval=approval,
            ),
        )
    )
    deny = _policy(
        (
            GovernancePolicyRule(
                rule_id="deny",
                priority=1,
                decision=GovernanceDecision.DENY,
            ),
        )
    )

    read = ToolBinding(uuid4(), "read", effect_type=ToolEffectType.READ)
    read_approval = ToolBinding(
        uuid4(),
        "read-approval",
        effect_type=ToolEffectType.READ,
        approval_required=True,
    )
    write_no_capability = ToolBinding(
        uuid4(),
        "write",
        effect_type=ToolEffectType.WRITE,
    )
    write_allowed = ToolBinding(
        uuid4(),
        "write-allowed",
        effect_type=ToolEffectType.WRITE,
        allow_no_approval_execution=True,
    )
    external_allowed = ToolBinding(
        uuid4(),
        "external",
        effect_type=ToolEffectType.EXTERNAL_SIDE_EFFECT,
        allow_no_approval_execution=True,
    )
    destructive = ToolBinding(
        uuid4(),
        "destroy",
        effect_type=ToolEffectType.DESTRUCTIVE,
    )

    def evaluate(
        binding: ToolBinding,
        policy: GovernancePolicyVersion = allow,
    ):
        return evaluate_policy(
            policy,
            principal=principal,
            agent_version_id=agent_version_id,
            binding=binding,
        )

    read_allow = evaluate(read)
    assert read_allow.effective_decision is GovernanceDecision.ALLOW
    assert read_allow.approval is None

    assert evaluate(read_approval).effective_decision is GovernanceDecision.DENY
    assert evaluate(write_no_capability).effective_decision is GovernanceDecision.DENY
    assert evaluate(destructive).effective_decision is GovernanceDecision.DENY

    read_pending = evaluate(read_approval, allow_with_fallback)
    write_pending = evaluate(write_no_capability, allow_with_fallback)
    destructive_pending = evaluate(destructive, allow_with_fallback)
    assert read_pending.effective_decision is GovernanceDecision.REQUIRE_APPROVAL
    assert write_pending.effective_decision is GovernanceDecision.REQUIRE_APPROVAL
    assert destructive_pending.effective_decision is GovernanceDecision.REQUIRE_APPROVAL
    assert read_pending.approval == approval
    assert write_pending.approval == approval
    assert destructive_pending.approval == approval

    write_allow = evaluate(write_allowed, allow_with_fallback)
    external_allow = evaluate(external_allowed, allow_with_fallback)
    assert write_allow.effective_decision is GovernanceDecision.ALLOW
    assert external_allow.effective_decision is GovernanceDecision.ALLOW
    assert write_allow.approval is None
    assert external_allow.approval is None
    assert evaluate(destructive, deny).effective_decision is GovernanceDecision.DENY

def test_draft_and_malformed_policy_fail_closed_but_retired_pinned_policy_still_evaluates() -> None:
    principal = _principal()
    agent_version_id = uuid4()
    binding = ToolBinding(uuid4(), "read", effect_type=ToolEffectType.READ)
    rule = GovernancePolicyRule(
        rule_id="allow",
        priority=1,
        decision=GovernanceDecision.ALLOW,
    )

    draft = evaluate_policy(
        _policy((rule,), status=GovernancePolicyStatus.DRAFT),
        principal=principal,
        agent_version_id=agent_version_id,
        binding=binding,
    )
    assert draft.effective_decision is GovernanceDecision.DENY

    retired = evaluate_policy(
        _policy((rule,), status=GovernancePolicyStatus.RETIRED),
        principal=principal,
        agent_version_id=agent_version_id,
        binding=binding,
    )
    assert retired.effective_decision is GovernanceDecision.ALLOW
    assert retired.matched_rule_id == "allow"

    malformed_policy = _policy((rule,))
    object.__setattr__(malformed_policy, "rules", ("malformed",))
    malformed = evaluate_policy(
        malformed_policy,
        principal=principal,
        agent_version_id=agent_version_id,
        binding=binding,
    )
    assert malformed.effective_decision is GovernanceDecision.DENY
    assert malformed.matched_rule_id is None
