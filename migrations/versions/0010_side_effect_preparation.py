"""add Stage 3.2 side-effect preparation capability

Revision ID: 0010_side_effect_preparation
Revises: 0009_external_action_intent
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_side_effect_preparation"
down_revision: str | None = "0009_external_action_intent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    reconciliation_mode = postgresql.ENUM(
        "AUTHORITATIVE",
        "BEST_EFFORT",
        "NONE",
        name="reconciliation_mode",
    )
    reconciliation_mode.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "tool_versions",
        sa.Column(
            "approval_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "tool_versions",
        sa.Column(
            "allow_no_approval_execution",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "tool_versions",
        sa.Column("credential_ref", sa.String(length=300), nullable=True),
    )
    op.add_column(
        "tool_versions",
        sa.Column(
            "idempotency_supported",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "tool_versions",
        sa.Column(
            "reconciliation_mode",
            postgresql.ENUM(
                "AUTHORITATIVE",
                "BEST_EFFORT",
                "NONE",
                name="reconciliation_mode",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'NONE'"),
        ),
    )

    op.create_check_constraint(
        "ck_tool_versions_approval_execution_exclusive",
        "tool_versions",
        "NOT (approval_required AND allow_no_approval_execution)",
    )
    op.create_check_constraint(
        "ck_tool_versions_nonblank_credential_ref",
        "tool_versions",
        "credential_ref IS NULL OR length(btrim(credential_ref)) > 0",
    )
    op.create_check_constraint(
        "ck_tool_versions_destructive_not_stage32_executable",
        "tool_versions",
        "effect_type <> 'DESTRUCTIVE' OR NOT allow_no_approval_execution",
    )
    op.create_check_constraint(
        "ck_tool_versions_read_not_side_effect_executable",
        "tool_versions",
        "effect_type <> 'READ' OR NOT allow_no_approval_execution",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_tool_versions_read_not_side_effect_executable",
        "tool_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_tool_versions_destructive_not_stage32_executable",
        "tool_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_tool_versions_nonblank_credential_ref",
        "tool_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_tool_versions_approval_execution_exclusive",
        "tool_versions",
        type_="check",
    )
    op.drop_column("tool_versions", "reconciliation_mode")
    op.drop_column("tool_versions", "idempotency_supported")
    op.drop_column("tool_versions", "credential_ref")
    op.drop_column("tool_versions", "allow_no_approval_execution")
    op.drop_column("tool_versions", "approval_required")
    postgresql.ENUM(name="reconciliation_mode").drop(op.get_bind(), checkfirst=True)
