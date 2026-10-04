"""enforce Wave-1 Run terminal row shape

Revision ID: 0005_run_terminal_shape
Revises: 0004_active_progression
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_run_terminal_shape"
down_revision: str | None = "0004_active_progression"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_runs_completed_shape",
        "runs",
        "status <> 'COMPLETED' OR "
        "(completed_at IS NOT NULL AND final_output IS NOT NULL AND failure_reason IS NULL)",
    )
    op.create_check_constraint(
        "ck_runs_failed_shape",
        "runs",
        "status <> 'FAILED' OR "
        "(completed_at IS NOT NULL AND failure_reason IS NOT NULL AND final_output IS NULL)",
    )
    op.create_check_constraint(
        "ck_runs_nonterminal_has_no_completed_at",
        "runs",
        "status NOT IN ('CREATED', 'QUEUED', 'RUNNING') OR completed_at IS NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_runs_nonterminal_has_no_completed_at", "runs", type_="check")
    op.drop_constraint("ck_runs_failed_shape", "runs", type_="check")
    op.drop_constraint("ck_runs_completed_shape", "runs", type_="check")
