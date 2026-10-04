from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from agentforge.infrastructure.db.execution_recorder import build_owned_run_stmt
from agentforge.infrastructure.db.models import Base
from agentforge.infrastructure.db.runtime_store import (
    _lease_deadline_expr,
    build_claim_candidate_stmt,
)


def _compile(stmt) -> str:
    return str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).upper()


def test_claim_query_uses_skip_locked_and_wall_clock_database_time() -> None:
    sql = _compile(build_claim_candidate_stmt())
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "CLOCK_TIMESTAMP()" in sql
    assert "CURRENT_TIMESTAMP" not in sql
    assert "LEASE_EXPIRES_AT" in sql
    assert "AVAILABLE_AT" in sql


def test_progression_fence_requires_generation_live_lease_and_row_lock() -> None:
    sql = _compile(build_owned_run_stmt(run_id=uuid4(), expected_generation=7))
    assert "FOR UPDATE" in sql
    assert "EXECUTION_GENERATION = 7" in sql
    assert "LEASE_EXPIRES_AT" in sql
    assert "CLOCK_TIMESTAMP()" in sql


def test_lease_deadline_uses_database_wall_clock_not_transaction_start_time() -> None:
    sql = _compile(select(_lease_deadline_expr(30)))
    assert "CLOCK_TIMESTAMP()" in sql
    assert "INTERVAL '30 SECONDS'" in sql


def test_core_schema_contains_versioned_tool_bindings_and_durable_facts() -> None:
    expected = {
        "agents",
        "agent_versions",
        "tool_definitions",
        "tool_versions",
        "agent_version_tools",
        "idempotency_records",
        "runs",
        "run_states",
        "run_counters",
        "run_messages",
        "model_invocations",
        "tool_proposals",
        "tool_calls",
        "tool_execution_attempts",
        "domain_events",
    }
    assert expected.issubset(Base.metadata.tables)

    run_table = Base.metadata.tables["runs"]
    assert "execution_generation" in run_table.c
    assert "lease_expires_at" in run_table.c
    assert "available_at" in run_table.c
    assert "max_model_invocations" in run_table.c
    assert "max_tool_attempts" in run_table.c
    assert "deadline_at" in run_table.c

    run_state = Base.metadata.tables["run_states"]
    assert "model_invocations_used" in run_state.c
    assert "tool_attempts_used" in run_state.c

    tool_call = Base.metadata.tables["tool_calls"]
    assert len(tool_call.c.tool_version_id.foreign_keys) == 1


def test_model_invocation_schema_tracks_started_completed_failed_lifecycle() -> None:
    table = Base.metadata.tables["model_invocations"]
    assert {"status", "outcome_type", "error", "completed_at"}.issubset(set(table.c.keys()))
    assert table.c.outcome_type.nullable is True
    assert table.c.status.nullable is False


def test_only_denied_tool_calls_may_omit_tool_version_binding() -> None:
    table = Base.metadata.tables["tool_calls"]
    assert table.c.tool_version_id.nullable is True
    checks = {constraint.name for constraint in table.constraints if constraint.name}
    assert "ck_tool_calls_bound_version_unless_denied" in checks


def test_tool_version_has_bounded_read_retry_policy() -> None:
    table = Base.metadata.tables["tool_versions"]
    assert {
        "read_retry_max_attempts",
        "read_retry_initial_backoff_seconds",
        "read_retry_max_backoff_seconds",
    }.issubset(table.c.keys())
    checks = {constraint.name for constraint in table.constraints if constraint.name}
    assert {
        "ck_tool_versions_positive_read_retry_attempts",
        "ck_tool_versions_nonnegative_read_retry_initial_backoff",
        "ck_tool_versions_read_retry_backoff_order",
    }.issubset(checks)


def test_agent_version_tool_binding_remains_non_nullable() -> None:
    table = Base.metadata.tables["agent_version_tools"]
    assert table.c.tool_version_id.nullable is False


def test_core_schema_enforces_one_active_tool_call_per_run() -> None:
    table = Base.metadata.tables["tool_calls"]
    indexes = {index.name: index for index in table.indexes}
    active = indexes["uq_tool_calls_one_active_per_run"]
    assert active.unique is True
    assert [column.name for column in active.columns] == ["run_id"]
    where = str(active.dialect_options["postgresql"]["where"]).upper()
    assert "READY" in where
    assert "EXECUTING" in where


def test_core_schema_enforces_one_started_model_invocation_per_run() -> None:
    table = Base.metadata.tables["model_invocations"]
    indexes = {index.name: index for index in table.indexes}
    active = indexes["uq_model_invocations_one_started_per_run"]
    assert active.unique is True
    assert [column.name for column in active.columns] == ["run_id"]
    where = str(active.dialect_options["postgresql"]["where"]).upper()
    assert "STATUS = 'STARTED'" in where


def test_tool_execution_attempt_schema_enforces_physical_attempt_invariants() -> None:
    table = Base.metadata.tables["tool_execution_attempts"]
    assert {
        "run_id",
        "tool_call_id",
        "attempt_number",
        "execution_generation",
        "status",
        "finished_at",
    }.issubset(table.c.keys())
    indexes = {index.name: index for index in table.indexes}
    started = indexes["uq_tool_execution_attempts_one_started_per_call"]
    assert started.unique is True
    assert [column.name for column in started.columns] == ["tool_call_id"]
    where = str(started.dialect_options["postgresql"]["where"]).upper()
    assert "STATUS = 'STARTED'" in where
    unique_names = {
        constraint.name for constraint in table.constraints if constraint.name is not None
    }
    assert "uq_tool_execution_attempts_call_number" in unique_names


def test_run_schema_enforces_terminal_row_shape() -> None:
    table = Base.metadata.tables["runs"]
    checks = {constraint.name for constraint in table.constraints if constraint.name}
    assert {
        "ck_runs_completed_shape",
        "ck_runs_failed_shape",
        "ck_runs_nonterminal_has_no_completed_at",
    }.issubset(checks)


def test_run_limits_have_positive_and_nonnegative_database_guards() -> None:
    run_table = Base.metadata.tables["runs"]
    run_checks = {
        constraint.name for constraint in run_table.constraints if constraint.name is not None
    }
    assert "ck_runs_positive_model_budget" in run_checks
    assert "ck_runs_positive_tool_budget" in run_checks

    state_table = Base.metadata.tables["run_states"]
    state_checks = {
        constraint.name for constraint in state_table.constraints if constraint.name is not None
    }
    assert "ck_run_states_nonnegative_model_usage" in state_checks
    assert "ck_run_states_nonnegative_tool_usage" in state_checks
