import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_alembic_offline_upgrade_compiles_core_schema_and_model_lifecycle() -> None:
    env = os.environ.copy()
    env.setdefault(
        "AGENTFORGE_DATABASE_URL",
        "postgresql+psycopg://agentforge:agentforge@localhost:5432/agentforge",
    )
    result = subprocess.run(
        ["alembic", "upgrade", "head", "--sql"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    ddl = result.stdout.upper()
    assert "CREATE TABLE RUNS" in ddl
    assert "CREATE TABLE MODEL_INVOCATIONS" in ddl
    assert "ADD COLUMN STATUS VARCHAR(32)" in ddl
    assert "ADD COLUMN ERROR TEXT" in ddl
    assert "ADD COLUMN COMPLETED_AT TIMESTAMP WITH TIME ZONE" in ddl
    assert "0002_MODEL_INVOCATION_LIFECYCLE" in ddl
    assert "0003_DENIED_TOOL_CALLS" in ddl
    assert "ALTER TABLE TOOL_CALLS ALTER COLUMN TOOL_VERSION_ID DROP NOT NULL" in ddl
    assert "CK_TOOL_CALLS_BOUND_VERSION_UNLESS_DENIED" in ddl
    assert "0004_ACTIVE_PROGRESSION" in ddl
    assert "UQ_TOOL_CALLS_ONE_ACTIVE_PER_RUN" in ddl
    assert "UQ_MODEL_INVOCATIONS_ONE_STARTED_PER_RUN" in ddl
    assert "WHERE STATUS IN ('READY', 'EXECUTING')" in ddl
    assert "0005_RUN_TERMINAL_SHAPE" in ddl
    assert "CK_RUNS_COMPLETED_SHAPE" in ddl
    assert "CK_RUNS_FAILED_SHAPE" in ddl
    assert "CK_RUNS_NONTERMINAL_HAS_NO_COMPLETED_AT" in ddl
    assert "0006_TOOL_ATTEMPTS" in ddl
    assert "CREATE TABLE TOOL_EXECUTION_ATTEMPTS" in ddl
    assert "UQ_TOOL_EXECUTION_ATTEMPTS_ONE_STARTED_PER_CALL" in ddl
    assert "0007_RUN_LIMITS" in ddl
    assert "MAX_MODEL_INVOCATIONS" in ddl
    assert "MAX_TOOL_ATTEMPTS" in ddl
    assert "DEADLINE_AT" in ddl
    assert "MODEL_INVOCATIONS_USED" in ddl
    assert "TOOL_ATTEMPTS_USED" in ddl
    assert "0008_READ_RETRY_POLICY" in ddl
    assert "READ_RETRY_MAX_ATTEMPTS" in ddl
    assert "CK_TOOL_VERSIONS_POSITIVE_READ_RETRY_ATTEMPTS" in ddl
    assert "0009_EXTERNAL_ACTION_INTENT" in ddl
    assert "CREATE TABLE ACTION_SNAPSHOTS" in ddl
    assert "CREATE TABLE EXTERNAL_ACTIONS" in ddl
    assert "UQ_EXTERNAL_ACTIONS_ONE_NONTERMINAL_PER_RUN" in ddl
    assert "FK_TOOL_EXECUTION_ATTEMPTS_EXTERNAL_ACTION" in ddl


def test_run_terminal_shape_migration_is_present() -> None:
    migration = (ROOT / "migrations" / "versions" / "0005_run_terminal_shape.py").read_text()
    assert 'revision: str = "0005_run_terminal_shape"' in migration
    assert 'down_revision: str | None = "0004_active_progression"' in migration
    assert "ck_runs_completed_shape" in migration
    assert "ck_runs_failed_shape" in migration
    assert "ck_runs_nonterminal_has_no_completed_at" in migration


def test_alembic_online_url_supports_environment_with_explicit_caller_precedence() -> None:
    env_py = (ROOT / "migrations" / "env.py").read_text()
    assert 'os.getenv("AGENTFORGE_DATABASE_URL")' in env_py
    assert 'config.attributes.get("agentforge_explicit_database_url")' in env_py
    assert 'explicit_database_url or os.getenv("AGENTFORGE_DATABASE_URL")' in env_py
    assert 'config.set_main_option("sqlalchemy.url", str(database_url))' in env_py


def test_stage32_a2_run_limit_migration_is_forward_only_from_attempt_head() -> None:
    migration = (ROOT / "migrations" / "versions" / "0007_run_limits.py").read_text()
    assert 'revision: str = "0007_run_limits"' in migration
    assert 'down_revision: str | None = "0006_tool_attempts"' in migration
    assert "clock_timestamp()" in migration
    assert "max_model_invocations" in migration
    assert "max_tool_attempts" in migration
    assert "deadline_at" in migration
