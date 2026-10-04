"""add durable tool execution attempts

Revision ID: 0006_tool_attempts
Revises: 0005_run_terminal_shape
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_tool_attempts"
down_revision: str | None = "0005_run_terminal_shape"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    status = postgresql.ENUM(
        "STARTED",
        "SUCCEEDED",
        "FAILED",
        "UNKNOWN",
        name="tool_execution_attempt_status",
    )
    status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "tool_execution_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "tool_call_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tool_calls.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("external_action_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("execution_generation", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "STARTED",
                "SUCCEEDED",
                "FAILED",
                "UNKNOWN",
                name="tool_execution_attempt_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("error_class", sa.String(length=64), nullable=True),
        sa.Column("outcome_reason", sa.String(length=120), nullable=True),
        sa.Column("definite_not_executed", sa.Boolean(), nullable=True),
        sa.Column("adapter_metadata", postgresql.JSONB(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "tool_call_id",
            "attempt_number",
            name="uq_tool_execution_attempts_call_number",
        ),
    )
    op.create_index(
        "uq_tool_execution_attempts_one_started_per_call",
        "tool_execution_attempts",
        ["tool_call_id"],
        unique=True,
        postgresql_where=sa.text("status = 'STARTED'"),
    )
    op.create_index(
        "ix_tool_execution_attempts_run_id",
        "tool_execution_attempts",
        ["run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tool_execution_attempts_run_id",
        table_name="tool_execution_attempts",
    )
    op.drop_index(
        "uq_tool_execution_attempts_one_started_per_call",
        table_name="tool_execution_attempts",
    )
    op.drop_table("tool_execution_attempts")
    postgresql.ENUM(name="tool_execution_attempt_status").drop(op.get_bind(), checkfirst=True)
