"""add side-effect UNKNOWN ToolCall projection

Revision ID: 0011_side_effect_unknown
Revises: 0010_side_effect_preparation
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011_side_effect_unknown"
down_revision: str | None = "0010_side_effect_preparation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE tool_call_status ADD VALUE IF NOT EXISTS 'UNRESOLVED'")


def downgrade() -> None:
    # PostgreSQL enum-value removal requires type recreation. Stage 3.2 migrations
    # preserve enum history rather than rewrite accepted prior values.
    pass
