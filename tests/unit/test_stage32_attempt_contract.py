from pathlib import Path
from uuid import uuid4

from agentforge.domain.enums import ToolExecutionAttemptStatus
from agentforge.domain.models import ToolExecutionAttempt

ROOT = Path(__file__).resolve().parents[2]


def test_tool_execution_attempt_domain_lifecycle() -> None:
    attempt = ToolExecutionAttempt(
        uuid4(),
        uuid4(),
        uuid4(),
        1,
        7,
    )
    assert attempt.status is ToolExecutionAttemptStatus.STARTED
    attempt.succeed({"ok": True})
    assert attempt.status is ToolExecutionAttemptStatus.SUCCEEDED
    assert attempt.finished_at is not None


def test_stage32_a1_migration_is_forward_only_from_stage31_head() -> None:
    migration = (ROOT / "migrations" / "versions" / "0006_tool_attempts.py").read_text()
    assert 'revision: str = "0006_tool_attempts"' in migration
    assert 'down_revision: str | None = "0005_run_terminal_shape"' in migration
    assert "tool_execution_attempts" in migration
    assert "uq_tool_execution_attempts_one_started_per_call" in migration
