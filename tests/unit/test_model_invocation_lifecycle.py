from uuid import uuid4

import pytest

from agentforge.domain.enums import ModelInvocationStatus
from agentforge.domain.models import ModelInvocation


def test_model_invocation_completes_exactly_once() -> None:
    invocation = ModelInvocation(uuid4(), uuid4(), 1)
    assert invocation.status is ModelInvocationStatus.STARTED

    invocation.complete("FINAL")
    assert invocation.status is ModelInvocationStatus.COMPLETED
    assert invocation.outcome_type == "FINAL"
    assert invocation.completed_at is not None

    with pytest.raises(ValueError):
        invocation.complete("TOOL_PROPOSAL")


def test_model_invocation_failure_is_terminal() -> None:
    invocation = ModelInvocation(uuid4(), uuid4(), 2)
    invocation.fail("timeout")
    assert invocation.status is ModelInvocationStatus.FAILED
    assert invocation.error == "timeout"
    assert invocation.completed_at is not None

    with pytest.raises(ValueError):
        invocation.complete("FINAL")
