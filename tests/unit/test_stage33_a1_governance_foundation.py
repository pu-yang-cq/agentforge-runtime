from dataclasses import dataclass
from uuid import uuid4

import pytest

from agentforge.application.principals import (
    LegacyDevelopmentPrincipalResolver,
    resolve_principal_for_mode,
)
from agentforge.domain.enums import (
    GovernanceDecision,
    GovernanceMode,
    PrincipalType,
    ToolEffectType,
)
from agentforge.domain.governance import (
    GovernanceApprovalRequirement,
    GovernancePolicyRule,
    PrincipalContext,
    normalize_policy_rules,
)
from agentforge.domain.models import AgentVersion


def test_principal_context_normalizes_identity_scope_authn_and_roles() -> None:
    principal = PrincipalContext(
        principal_id="  user-17 ",
        principal_type=PrincipalType.USER,
        roles=(" runtime:run:create ", "approver", "approver"),
        principal_scope=" tenant-a ",
        authn_source=" oidc ",
    )
    assert principal.principal_id == "user-17"
    assert principal.principal_scope == "tenant-a"
    assert principal.authn_source == "oidc"
    assert principal.roles == ("approver", "runtime:run:create")


def test_principal_context_rejects_blank_authority_fields() -> None:
    with pytest.raises(ValueError):
        PrincipalContext(
            principal_id=" ",
            principal_type=PrincipalType.USER,
            roles=(),
            principal_scope="tenant-a",
            authn_source="oidc",
        )
    with pytest.raises(ValueError):
        PrincipalContext(
            principal_id="user",
            principal_type=PrincipalType.USER,
            roles=(),
            principal_scope=" ",
            authn_source="oidc",
        )
    with pytest.raises(ValueError):
        PrincipalContext(
            principal_id="user",
            principal_type=PrincipalType.USER,
            roles=(),
            principal_scope="tenant-a",
            authn_source=" ",
        )


def test_policy_rule_schema_is_bounded_normalized_and_requires_approval_metadata() -> None:
    agent_id = uuid4()
    tool_id = uuid4()
    approval = GovernanceApprovalRequirement(" approver ", True, 600)
    rule = GovernancePolicyRule(
        rule_id=" allow-write ",
        priority=10,
        principal_roles_any=(" operator ", "operator"),
        agent_version_ids=(agent_id, agent_id),
        tool_version_ids=(tool_id,),
        effect_types=(ToolEffectType.WRITE,),
        principal_scopes=(" tenant-a ",),
        decision=GovernanceDecision.REQUIRE_APPROVAL,
        approval=approval,
    )
    assert rule.rule_id == "allow-write"
    assert rule.principal_roles_any == ("operator",)
    assert rule.agent_version_ids == (agent_id,)
    assert rule.approval is not None
    assert rule.approval.required_approver_role == "approver"
    assert GovernancePolicyRule.from_record(rule.to_record()) == rule

    with pytest.raises(ValueError):
        GovernancePolicyRule(
            rule_id="needs-approval",
            priority=1,
            decision=GovernanceDecision.REQUIRE_APPROVAL,
        )
    with pytest.raises(ValueError):
        normalize_policy_rules((rule, rule))


def test_agent_version_governance_shape_defaults_legacy_and_requires_governed_pin() -> None:
    policy_id = uuid4()
    legacy = AgentVersion(uuid4(), uuid4(), 1, "legacy")
    assert legacy.governance_mode is GovernanceMode.LEGACY_STAGE32
    assert legacy.policy_version_id is None

    governed = AgentVersion(
        uuid4(),
        uuid4(),
        2,
        "governed",
        governance_mode=GovernanceMode.GOVERNED,
        policy_version_id=policy_id,
    )
    assert governed.policy_version_id == policy_id

    with pytest.raises(ValueError):
        AgentVersion(
            uuid4(),
            uuid4(),
            3,
            "invalid",
            governance_mode=GovernanceMode.GOVERNED,
        )


@dataclass(frozen=True, slots=True)
class _TrustedResolver:
    @property
    def trusted_for_governed(self) -> bool:
        return True

    def resolve(self) -> PrincipalContext:
        return PrincipalContext(
            principal_id="trusted-user",
            principal_type=PrincipalType.USER,
            roles=("runtime:run:create",),
            principal_scope="tenant-a",
            authn_source="test-trusted",
        )


def test_legacy_principal_resolver_is_non_authoritative_for_governed_mode() -> None:
    legacy = LegacyDevelopmentPrincipalResolver(principal_scope="legacy-scope")
    assert resolve_principal_for_mode(legacy, GovernanceMode.LEGACY_STAGE32).principal_scope == (
        "legacy-scope"
    )
    with pytest.raises(PermissionError):
        resolve_principal_for_mode(legacy, GovernanceMode.GOVERNED)

    trusted = resolve_principal_for_mode(_TrustedResolver(), GovernanceMode.GOVERNED)
    assert trusted.principal_id == "trusted-user"
