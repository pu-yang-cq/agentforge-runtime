from uuid import uuid4

import pytest

from agentforge.domain.enums import RunStatus
from agentforge.domain.models import Run


def test_run_happy_state_machine() -> None:
    run = Run(uuid4(), uuid4(), "hello")
    assert run.status is RunStatus.CREATED
    run.queue()
    assert run.status is RunStatus.QUEUED
    run.start()
    assert run.status is RunStatus.RUNNING
    run.complete("done")
    assert run.status is RunStatus.COMPLETED
    assert run.final_output == "done"


def test_terminal_run_cannot_restart() -> None:
    run = Run(uuid4(), uuid4(), "hello")
    run.queue()
    run.start()
    run.complete("done")
    with pytest.raises(ValueError):
        run.start()
