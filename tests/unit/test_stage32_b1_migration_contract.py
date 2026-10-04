from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_stage32_b1_migration_is_forward_only_from_read_retry_head() -> None:
    migration = (ROOT / "migrations" / "versions" / "0009_external_action_intent.py").read_text()
    assert 'revision: str = "0009_external_action_intent"' in migration
    assert 'down_revision: str | None = "0008_read_retry_policy"' in migration
    assert "action_snapshots" in migration
    assert "external_actions" in migration
    assert "uq_external_actions_one_nonterminal_per_run" in migration
    assert "fk_tool_execution_attempts_external_action" in migration
