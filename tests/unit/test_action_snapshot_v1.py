from uuid import UUID, uuid4

import pytest

from agentforge.domain.actions import (
    MAX_SAFE_INTEGER,
    ActionSnapshot,
    ExternalAction,
    canonical_json_v1,
)
from agentforge.domain.enums import ExternalActionStatus, ToolEffectType


def test_action_snapshot_v1_golden_bytes_and_digest() -> None:
    snapshot = ActionSnapshot.create(
        operation_id=UUID("123e4567-e89b-12d3-a456-426614174000"),
        tool_version_id=UUID("123e4567-e89b-12d3-a456-426614174001"),
        effect_type=ToolEffectType.EXTERNAL_SIDE_EFFECT,
        credential_ref="cred:crm-prod",
        arguments={
            "customer_id": "c-123",
            "count": 2,
            "flags": [True, None, "x"],
        },
    )
    expected = (
        '{"arguments":{"count":2,"customer_id":"c-123","flags":[true,null,"x"]},'
        '"credential_ref":"cred:crm-prod","effect_type":"EXTERNAL_SIDE_EFFECT",'
        '"format_version":1,"operation_id":"123e4567-e89b-12d3-a456-426614174000",'
        '"tool_version_id":"123e4567-e89b-12d3-a456-426614174001"}'
    )
    assert snapshot.canonical_json == expected
    assert snapshot.digest == "c596747972eee80b08adabeb1cb519e174ef74297e455ff854488afb3242e89f"


def test_action_snapshot_v1_rejects_float_unsafe_integer_and_non_string_key() -> None:
    with pytest.raises(ValueError, match="floating-point"):
        canonical_json_v1({"amount": 1.5})
    with pytest.raises(ValueError, match="safe range"):
        canonical_json_v1({"amount": MAX_SAFE_INTEGER + 1})
    with pytest.raises(ValueError, match="keys must be strings"):
        canonical_json_v1({1: "no"})


def test_action_snapshot_v1_uses_utf16_member_order() -> None:
    # U+10000 sorts before U+E000 by UTF-16 code units although its scalar
    # value is larger. This guards the RFC 8785 member-order rule.
    encoded = canonical_json_v1({"": 1, "𐀀": 2}).decode("utf-8")
    assert encoded == '{"𐀀":2,"":1}'


def test_external_action_starts_ready_with_stable_operation_identity() -> None:
    operation_id = uuid4()
    action = ExternalAction.create(
        run_id=uuid4(),
        tool_call_id=uuid4(),
        action_snapshot_id=uuid4(),
        operation_id=operation_id,
    )
    assert action.operation_id == operation_id
    assert action.status is ExternalActionStatus.READY
    assert action.current_attempt_id is None
