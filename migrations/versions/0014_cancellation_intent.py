"""add durable cancellation intent

Revision ID: 0014_cancellation_intent
Revises: 0013_reconciliation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_cancellation_intent"
down_revision: str | None = "0013_reconciliation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column(
            "cancel_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.alter_column("runs", "cancel_requested", server_default=None)


def downgrade() -> None:
    op.drop_column("runs", "cancel_requested")
