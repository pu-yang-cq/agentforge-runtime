"""add ActionSnapshot V1 and ExternalAction durable intent

Revision ID: 0009_external_action_intent
Revises: 0008_read_retry_policy
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_external_action_intent"
down_revision: str | None = "0008_read_retry_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE tool_effect_type ADD VALUE IF NOT EXISTS 'WRITE'")
    op.execute("ALTER TYPE tool_effect_type ADD VALUE IF NOT EXISTS 'EXTERNAL_SIDE_EFFECT'")
    op.execute("ALTER TYPE tool_effect_type ADD VALUE IF NOT EXISTS 'DESTRUCTIVE'")

    action_status = postgresql.ENUM(
        "READY",
        "EXECUTING",
        "UNKNOWN",
        "RECONCILING",
        "MANUAL_REVIEW",
        "SUCCEEDED",
        "FAILED",
        "ABORTED",
        name="external_action_status",
    )
    action_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "action_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("format_version", sa.Integer(), nullable=False),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tool_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tool_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "effect_type",
            postgresql.ENUM(
                "READ",
                "WRITE",
                "EXTERNAL_SIDE_EFFECT",
                "DESTRUCTIVE",
                name="tool_effect_type",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("credential_ref", sa.String(length=300), nullable=True),
        sa.Column("arguments", postgresql.JSONB(), nullable=False),
        sa.Column("canonical_json", sa.Text(), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("format_version = 1", name="ck_action_snapshots_format_v1"),
        sa.UniqueConstraint("operation_id", name="uq_action_snapshots_operation_id"),
    )

    op.create_table(
        "external_actions",
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
        sa.Column(
            "action_snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("action_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "READY",
                "EXECUTING",
                "UNKNOWN",
                "RECONCILING",
                "MANUAL_REVIEW",
                "SUCCEEDED",
                "FAILED",
                "ABORTED",
                name="external_action_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("current_attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("operation_id", name="uq_external_actions_operation_id"),
        sa.UniqueConstraint("tool_call_id", name="uq_external_actions_tool_call_id"),
        sa.UniqueConstraint("action_snapshot_id", name="uq_external_actions_snapshot_id"),
        sa.CheckConstraint(
            "(status = 'EXECUTING' AND current_attempt_id IS NOT NULL) OR "
            "(status <> 'EXECUTING' AND current_attempt_id IS NULL)",
            name="ck_external_actions_current_attempt_shape",
        ),
    )
    op.create_index(
        "uq_external_actions_one_nonterminal_per_run",
        "external_actions",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('READY', 'EXECUTING', 'UNKNOWN', 'RECONCILING', 'MANUAL_REVIEW')"
        ),
    )
    op.create_foreign_key(
        "fk_external_actions_current_attempt",
        "external_actions",
        "tool_execution_attempts",
        ["current_attempt_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_tool_execution_attempts_external_action",
        "tool_execution_attempts",
        "external_actions",
        ["external_action_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_tool_execution_attempts_external_action",
        "tool_execution_attempts",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_external_actions_current_attempt",
        "external_actions",
        type_="foreignkey",
    )
    op.drop_index(
        "uq_external_actions_one_nonterminal_per_run",
        table_name="external_actions",
    )
    op.drop_table("external_actions")
    op.drop_table("action_snapshots")
    postgresql.ENUM(name="external_action_status").drop(op.get_bind(), checkfirst=True)
