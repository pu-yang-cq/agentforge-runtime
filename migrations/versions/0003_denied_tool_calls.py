"""persist denied tool calls without a bound tool version

Revision ID: 0003_denied_tool_calls
Revises: 0002_model_invocation_lifecycle
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_denied_tool_calls"
down_revision: str | None = "0002_model_invocation_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "tool_calls",
        "tool_version_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.create_check_constraint(
        "ck_tool_calls_bound_version_unless_denied",
        "tool_calls",
        "status = 'DENIED' OR tool_version_id IS NOT NULL",
    )


def downgrade() -> None:
    # Legacy schema cannot represent an unbound DENIED ToolCall. Remove only
    # those rows rather than manufacturing a fake ToolVersion identity.
    op.execute("DELETE FROM tool_calls WHERE tool_version_id IS NULL")
    op.drop_constraint(
        "ck_tool_calls_bound_version_unless_denied",
        "tool_calls",
        type_="check",
    )
    op.alter_column(
        "tool_calls",
        "tool_version_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
