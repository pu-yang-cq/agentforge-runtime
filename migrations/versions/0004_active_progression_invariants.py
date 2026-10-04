"""enforce one active Wave-1 progression boundary per Run

Revision ID: 0004_active_progression
Revises: 0003_denied_tool_calls
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_active_progression"
down_revision: str | None = "0003_denied_tool_calls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_model_invocations_one_started_per_run",
        "model_invocations",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text("status = 'STARTED'"),
    )
    op.create_index(
        "uq_tool_calls_one_active_per_run",
        "tool_calls",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('READY', 'EXECUTING')"),
    )


def downgrade() -> None:
    op.drop_index("uq_tool_calls_one_active_per_run", table_name="tool_calls")
    op.drop_index(
        "uq_model_invocations_one_started_per_run",
        table_name="model_invocations",
    )
