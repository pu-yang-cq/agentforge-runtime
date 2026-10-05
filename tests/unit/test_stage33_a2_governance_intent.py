from uuid import UUID

import pytest

from agentforge.domain.enums import PrincipalType, ToolEffectType
from agentforge.domain.governance import PrincipalContext
from agentforge.domain.governance_decisions import GovernanceIntentV1
from agentforge.domain.models import ToolBinding

RUN_ID = UUID("00000000-0000-0000-0000-000000000001")
AGENT_VERSION_ID = UUID("00000000-0000-0000-0000-000000000002")
PROPOSAL_ID = UUID("00000000-0000-0000-0000-000000000003")
TOOL_VERSION_ID = UUID("00000000-0000-0000-0000-000000000004")

EXPECTED_CANONICAL = (
    '{"agent_version_id":"00000000-0000-0000-0000-000000000002",'
    '"arguments":{"a":{"alpha":"x","β":2},"z":[1,{"a":true,"é":"值"}]},'
    '"effect_type":"READ","format_version":1,"principal_scope":"tenant-a",'
    '"proposal_id":"00000000-0000-0000-0000-000000000003",'
    '"requester":{"principal_id":"user-1","principal_type":"USER",'
    '"roles":["approver","operator"]},'
    '"run_id":"00000000-0000-0000-0000-000000000001",'
    '"tool_version_id":"00000000-0000-0000-0000-000000000004"}'
)
EXPECTED_DIGEST = "2596669fe9fbae6271d42c0f9ccec05733d3d9a5577c9102dd3b31552d5bda4a"


def _binding() -> ToolBinding:
    return ToolBinding(
        tool_version_id=TOOL_VERSION_ID,
        name="read",
        effect_type=ToolEffectType.READ,
        credential_ref="SECRET_SENTINEL_CREDENTIAL",
    )


def _principal(*roles: str) -> PrincipalContext:
    return PrincipalContext(
        principal_id=" user-1 ",
        principal_type=PrincipalType.USER,
        roles=roles,
        principal_scope=" tenant-a ",
        authn_source="oidc",
    )


def test_governance_intent_v1_matches_golden_canonical_bytes_and_digest() -> None:
    intent = GovernanceIntentV1.create(
        run_id=RUN_ID,
        agent_version_id=AGENT_VERSION_ID,
        proposal_id=PROPOSAL_ID,
        binding=_binding(),
        arguments={
            "z": [1, {"é": "值", "a": True}],
            "a": {"β": 2, "alpha": "x"},
        },
        principal=_principal("operator", "approver", "operator"),
    )

    assert intent.canonical_json == EXPECTED_CANONICAL
    assert intent.digest == EXPECTED_DIGEST
    assert intent.requester_roles == ("approver", "operator")
    assert "SECRET_SENTINEL_CREDENTIAL" not in intent.canonical_json


def test_equivalent_role_and_object_order_produce_identical_intent_digest() -> None:
    first = GovernanceIntentV1.create(
        run_id=RUN_ID,
        agent_version_id=AGENT_VERSION_ID,
        proposal_id=PROPOSAL_ID,
        binding=_binding(),
        arguments={"z": [1, {"é": "值", "a": True}], "a": {"β": 2, "alpha": "x"}},
        principal=_principal("operator", "approver"),
    )
    second = GovernanceIntentV1.create(
        run_id=RUN_ID,
        agent_version_id=AGENT_VERSION_ID,
        proposal_id=PROPOSAL_ID,
        binding=_binding(),
        arguments={"a": {"alpha": "x", "β": 2}, "z": [1, {"a": True, "é": "值"}]},
        principal=_principal("approver", "operator"),
    )

    assert second.canonical_json == first.canonical_json
    assert second.digest == first.digest


@pytest.mark.parametrize(
    "arguments",
    [
        {"float": 1.5},
        {"too_large": 2**53},
        {"too_small": -(2**53)},
    ],
)
def test_governance_intent_rejects_noncanonical_numeric_values(
    arguments: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        GovernanceIntentV1.create(
            run_id=RUN_ID,
            agent_version_id=AGENT_VERSION_ID,
            proposal_id=PROPOSAL_ID,
            binding=_binding(),
            arguments=arguments,
            principal=_principal("operator"),
        )
