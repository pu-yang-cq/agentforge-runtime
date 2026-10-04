"""add Stage 3.2-D3 reconciliation lifecycle and safety policy

Revision ID: 0013_reconciliation
Revises: 0012_side_effect_retry
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_reconciliation"
down_revision: str | None = "0012_side_effect_retry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PostgreSQL requires a newly added enum value to commit before it can be
    # referenced by later DDL such as the Run-state CHECK constraint below.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE run_status ADD VALUE IF NOT EXISTS 'WAITING_ACTION_RESOLUTION'")

    reconciliation_attempt_status = postgresql.ENUM(
        "STARTED",
        "SUCCEEDED",
        "FAILED",
        name="reconciliation_attempt_status",
    )
    reconciliation_attempt_status.create(op.get_bind(), checkfirst=True)
    reconciliation_business_result = postgresql.ENUM(
        "SUCCEEDED",
        "FAILED",
        "NOT_EXECUTED",
        "UNKNOWN",
        name="reconciliation_business_result",
    )
    reconciliation_business_result.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "tool_versions",
        sa.Column("reconciliation_max_attempts", sa.Integer(), nullable=False, server_default="3"),
    )
    op.add_column(
        "tool_versions",
        sa.Column(
            "reconciliation_initial_backoff_seconds",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "tool_versions",
        sa.Column(
            "reconciliation_max_backoff_seconds",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
    )
    op.create_check_constraint(
        "ck_tool_versions_positive_reconciliation_attempts",
        "tool_versions",
        "reconciliation_max_attempts > 0",
    )
    op.create_check_constraint(
        "ck_tool_versions_nonnegative_reconciliation_initial_backoff",
        "tool_versions",
        "reconciliation_initial_backoff_seconds >= 0",
    )
    op.create_check_constraint(
        "ck_tool_versions_reconciliation_backoff_order",
        "tool_versions",
        "reconciliation_max_backoff_seconds >= reconciliation_initial_backoff_seconds",
    )
    op.alter_column("tool_versions", "reconciliation_max_attempts", server_default=None)
    op.alter_column(
        "tool_versions",
        "reconciliation_initial_backoff_seconds",
        server_default=None,
    )
    op.alter_column(
        "tool_versions",
        "reconciliation_max_backoff_seconds",
        server_default=None,
    )

    op.drop_constraint("ck_runs_nonterminal_has_no_completed_at", "runs", type_="check")
    op.create_check_constraint(
        "ck_runs_nonterminal_has_no_completed_at",
        "runs",
        "status NOT IN ('CREATED', 'QUEUED', 'RUNNING', 'WAITING_ACTION_RESOLUTION') "
        "OR completed_at IS NULL",
    )

    op.create_table(
        "reconciliation_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "external_action_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("external_actions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("execution_generation", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "STARTED",
                "SUCCEEDED",
                "FAILED",
                name="reconciliation_attempt_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "business_result",
            postgresql.ENUM(
                "SUCCEEDED",
                "FAILED",
                "NOT_EXECUTED",
                "UNKNOWN",
                name="reconciliation_business_result",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column("evidence", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("outcome_reason", sa.String(length=120), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "external_action_id",
            "attempt_number",
            name="uq_reconciliation_attempts_action_number",
        ),
    )
    op.create_index(
        "uq_reconciliation_attempts_one_started_per_action",
        "reconciliation_attempts",
        ["external_action_id"],
        unique=True,
        postgresql_where=sa.text("status = 'STARTED'"),
    )
    op.create_index(
        "ix_reconciliation_attempts_run_id",
        "reconciliation_attempts",
        ["run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_reconciliation_attempts_run_id", table_name="reconciliation_attempts")
    op.drop_index(
        "uq_reconciliation_attempts_one_started_per_action",
        table_name="reconciliation_attempts",
    )
    op.drop_table("reconciliation_attempts")
    op.drop_constraint(
        "ck_tool_versions_reconciliation_backoff_order",
        "tool_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_tool_versions_nonnegative_reconciliation_initial_backoff",
        "tool_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_tool_versions_positive_reconciliation_attempts",
        "tool_versions",
        type_="check",
    )
    op.drop_column("tool_versions", "reconciliation_max_backoff_seconds")
    op.drop_column("tool_versions", "reconciliation_initial_backoff_seconds")
    op.drop_column("tool_versions", "reconciliation_max_attempts")
    postgresql.ENUM(name="reconciliation_business_result").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="reconciliation_attempt_status").drop(op.get_bind(), checkfirst=True)
