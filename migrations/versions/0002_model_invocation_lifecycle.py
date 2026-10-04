"""durable model invocation lifecycle

Revision ID: 0002_model_invocation_lifecycle
Revises: 0001_core_runtime
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_model_invocation_lifecycle"
down_revision: str | None = "0001_core_runtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_invocations",
        sa.Column("status", sa.String(32), nullable=True),
    )
    op.add_column(
        "model_invocations",
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.add_column(
        "model_invocations",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE model_invocations SET status = 'COMPLETED' WHERE status IS NULL")
    op.alter_column("model_invocations", "status", nullable=False)
    op.alter_column(
        "model_invocations",
        "outcome_type",
        existing_type=sa.String(50),
        nullable=True,
    )


def downgrade() -> None:
    # A STARTED/FAILED row has no valid legacy outcome_type, so fail closed instead
    # of manufacturing a fake result during downgrade.
    op.execute("DELETE FROM model_invocations WHERE status <> 'COMPLETED' OR outcome_type IS NULL")
    op.alter_column(
        "model_invocations",
        "outcome_type",
        existing_type=sa.String(50),
        nullable=False,
    )
    op.drop_column("model_invocations", "completed_at")
    op.drop_column("model_invocations", "error")
    op.drop_column("model_invocations", "status")
