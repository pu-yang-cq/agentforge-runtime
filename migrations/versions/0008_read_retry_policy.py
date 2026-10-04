"""add versioned READ retry policy

Revision ID: 0008_read_retry_policy
Revises: 0007_run_limits
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_read_retry_policy"
down_revision: str | None = "0007_run_limits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tool_versions",
        sa.Column(
            "read_retry_max_attempts",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "tool_versions",
        sa.Column(
            "read_retry_initial_backoff_seconds",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "tool_versions",
        sa.Column(
            "read_retry_max_backoff_seconds",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
    )
    op.create_check_constraint(
        "ck_tool_versions_positive_read_retry_attempts",
        "tool_versions",
        "read_retry_max_attempts > 0",
    )
    op.create_check_constraint(
        "ck_tool_versions_nonnegative_read_retry_initial_backoff",
        "tool_versions",
        "read_retry_initial_backoff_seconds >= 0",
    )
    op.create_check_constraint(
        "ck_tool_versions_read_retry_backoff_order",
        "tool_versions",
        "read_retry_max_backoff_seconds >= read_retry_initial_backoff_seconds",
    )
    op.alter_column("tool_versions", "read_retry_max_attempts", server_default=None)
    op.alter_column(
        "tool_versions",
        "read_retry_initial_backoff_seconds",
        server_default=None,
    )
    op.alter_column(
        "tool_versions",
        "read_retry_max_backoff_seconds",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_tool_versions_read_retry_backoff_order",
        "tool_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_tool_versions_nonnegative_read_retry_initial_backoff",
        "tool_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_tool_versions_positive_read_retry_attempts",
        "tool_versions",
        type_="check",
    )
    op.drop_column("tool_versions", "read_retry_max_backoff_seconds")
    op.drop_column("tool_versions", "read_retry_initial_backoff_seconds")
    op.drop_column("tool_versions", "read_retry_max_attempts")
