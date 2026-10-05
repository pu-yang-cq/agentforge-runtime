"""add optional Checkpoint V1 overlay

Revision ID: 0016_checkpoint_overlay
Revises: 0015_action_resolution
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_checkpoint_overlay"
down_revision: str | None = "0015_action_resolution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "run_checkpoints",
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("runner_version", sa.String(length=100), nullable=False),
        sa.Column("run_state_version", sa.Integer(), nullable=False),
        sa.Column("execution_spec_identity", sa.String(length=300), nullable=False),
        sa.Column("working_state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("message_high_water", sa.Integer(), nullable=False),
        sa.Column("event_high_water", sa.Integer(), nullable=False),
        sa.Column("context_cursor", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "schema_version > 0",
            name="ck_run_checkpoints_positive_schema",
        ),
        sa.CheckConstraint(
            "run_state_version >= 0",
            name="ck_run_checkpoints_nonnegative_state_version",
        ),
        sa.CheckConstraint(
            "message_high_water >= 0",
            name="ck_run_checkpoints_nonnegative_message_water",
        ),
        sa.CheckConstraint(
            "event_high_water >= 0",
            name="ck_run_checkpoints_nonnegative_event_water",
        ),
        sa.CheckConstraint(
            "length(btrim(runner_version)) > 0",
            name="ck_run_checkpoints_runner_nonblank",
        ),
        sa.CheckConstraint(
            "length(btrim(execution_spec_identity)) > 0",
            name="ck_run_checkpoints_execution_spec_nonblank",
        ),
    )


def downgrade() -> None:
    op.drop_table("run_checkpoints")
