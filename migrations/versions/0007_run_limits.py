"""add durable run budgets and deadline

Revision ID: 0007_run_limits
Revises: 0006_tool_attempts
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_run_limits"
down_revision: str | None = "0006_tool_attempts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_MAX_MODEL_INVOCATIONS = 16
DEFAULT_MAX_TOOL_ATTEMPTS = 32
DEFAULT_RUN_DEADLINE_SECONDS = 15 * 60


def upgrade() -> None:
    # Expand the frozen Stage 3.2 scheduling enum. PostgreSQL enum values are
    # intentionally left in place on downgrade because DROP VALUE is not a
    # supported safe migration operation.
    for value in (
        "APPROVAL_RESOLVED",
        "ACTION_RESOLVED",
        "YIELD",
        "RESCHEDULED",
    ):
        op.execute(sa.text(f"ALTER TYPE queue_reason ADD VALUE IF NOT EXISTS '{value}'"))

    op.add_column(
        "runs",
        sa.Column(
            "max_model_invocations",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "runs",
        sa.Column(
            "max_tool_attempts",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "runs",
        sa.Column(
            "deadline_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "run_states",
        sa.Column(
            "model_invocations_used",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "run_states",
        sa.Column(
            "tool_attempts_used",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    # Existing rows receive a migration-time deadline window. New Runs derive
    # deadline_at from PostgreSQL clock_timestamp() at creation.
    op.execute(
        sa.text(
            "UPDATE runs "
            f"SET max_model_invocations = {DEFAULT_MAX_MODEL_INVOCATIONS}, "
            f"max_tool_attempts = {DEFAULT_MAX_TOOL_ATTEMPTS}, "
            "deadline_at = clock_timestamp() + "
            f"INTERVAL '{DEFAULT_RUN_DEADLINE_SECONDS} seconds' "
            "WHERE max_model_invocations IS NULL "
            "OR max_tool_attempts IS NULL "
            "OR deadline_at IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE run_states AS rs "
            "SET model_invocations_used = counts.n "
            "FROM ("
            "  SELECT run_id, count(*)::integer AS n "
            "  FROM model_invocations GROUP BY run_id"
            ") AS counts "
            "WHERE rs.run_id = counts.run_id"
        )
    )
    op.execute(
        sa.text(
            "UPDATE run_states AS rs "
            "SET tool_attempts_used = counts.n "
            "FROM ("
            "  SELECT run_id, count(*)::integer AS n "
            "  FROM tool_execution_attempts GROUP BY run_id"
            ") AS counts "
            "WHERE rs.run_id = counts.run_id"
        )
    )

    op.alter_column("runs", "max_model_invocations", nullable=False)
    op.alter_column("runs", "max_tool_attempts", nullable=False)
    op.alter_column("runs", "deadline_at", nullable=False)

    op.create_check_constraint(
        "ck_runs_positive_model_budget",
        "runs",
        "max_model_invocations > 0",
    )
    op.create_check_constraint(
        "ck_runs_positive_tool_budget",
        "runs",
        "max_tool_attempts > 0",
    )
    op.create_check_constraint(
        "ck_run_states_nonnegative_model_usage",
        "run_states",
        "model_invocations_used >= 0",
    )
    op.create_check_constraint(
        "ck_run_states_nonnegative_tool_usage",
        "run_states",
        "tool_attempts_used >= 0",
    )

    op.alter_column(
        "run_states",
        "model_invocations_used",
        server_default=None,
    )
    op.alter_column(
        "run_states",
        "tool_attempts_used",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_run_states_nonnegative_tool_usage",
        "run_states",
        type_="check",
    )
    op.drop_constraint(
        "ck_run_states_nonnegative_model_usage",
        "run_states",
        type_="check",
    )
    op.drop_constraint(
        "ck_runs_positive_tool_budget",
        "runs",
        type_="check",
    )
    op.drop_constraint(
        "ck_runs_positive_model_budget",
        "runs",
        type_="check",
    )
    op.drop_column("run_states", "tool_attempts_used")
    op.drop_column("run_states", "model_invocations_used")
    op.drop_column("runs", "deadline_at")
    op.drop_column("runs", "max_tool_attempts")
    op.drop_column("runs", "max_model_invocations")
