"""add durable manual ActionResolution

Revision ID: 0015_action_resolution
Revises: 0014_cancellation_intent
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_action_resolution"
down_revision: str | None = "0014_cancellation_intent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    outcome = postgresql.ENUM(
        "SUCCEEDED",
        "FAILED",
        "ABORTED",
        name="action_resolution_outcome",
    )
    outcome.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "action_resolutions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_action_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "outcome",
            postgresql.ENUM(
                "SUCCEEDED",
                "FAILED",
                "ABORTED",
                name="action_resolution_outcome",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("resolver_identity", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "length(btrim(resolver_identity)) > 0",
            name="ck_action_resolutions_nonblank_resolver",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["external_action_id"],
            ["external_actions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "external_action_id",
            name="uq_action_resolutions_external_action",
        ),
    )
    op.create_index(
        "ix_action_resolutions_run_id",
        "action_resolutions",
        ["run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_action_resolutions_run_id", table_name="action_resolutions")
    op.drop_table("action_resolutions")
    postgresql.ENUM(name="action_resolution_outcome").drop(
        op.get_bind(),
        checkfirst=True,
    )
