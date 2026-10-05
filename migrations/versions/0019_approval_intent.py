"""add Stage 3.3-C durable approval intent

Revision ID: 0019_approval_intent
Revises: 0018_governance_decision
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019_approval_intent"
down_revision: str | None = "0018_governance_decision"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # These shared enums already exist on an accepted Stage 3.2/3.3-A database.
    # PostgreSQL requires newly added enum values to commit before later DDL can
    # reference them in constraints or partial-index predicates.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE run_status ADD VALUE IF NOT EXISTS 'WAITING_APPROVAL'")
        op.execute("ALTER TYPE tool_call_status ADD VALUE IF NOT EXISTS 'AWAITING_APPROVAL'")
        op.execute(
            "ALTER TYPE external_action_status ADD VALUE IF NOT EXISTS 'AWAITING_APPROVAL'"
        )

    approval_status = postgresql.ENUM(
        "PENDING",
        "APPROVED",
        "DENIED",
        "EXPIRED",
        "CANCELLED",
        name="approval_request_status",
    )
    approval_status.create(op.get_bind(), checkfirst=True)

    op.drop_constraint(
        "ck_runs_nonterminal_has_no_completed_at",
        "runs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_runs_nonterminal_has_no_completed_at",
        "runs",
        "status NOT IN ("
        "'CREATED', 'QUEUED', 'RUNNING', 'WAITING_ACTION_RESOLUTION', 'WAITING_APPROVAL'"
        ") OR completed_at IS NULL",
    )

    op.drop_index(
        "uq_tool_calls_one_active_per_run",
        table_name="tool_calls",
    )
    op.create_index(
        "uq_tool_calls_one_active_per_run",
        "tool_calls",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('AWAITING_APPROVAL', 'READY', 'EXECUTING')"
        ),
    )

    op.drop_index(
        "uq_external_actions_one_nonterminal_per_run",
        table_name="external_actions",
    )
    op.create_index(
        "uq_external_actions_one_nonterminal_per_run",
        "external_actions",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ("
            "'AWAITING_APPROVAL', 'READY', 'EXECUTING', 'UNKNOWN', "
            "'RECONCILING', 'MANUAL_REVIEW'"
            ")"
        ),
    )

    op.create_table(
        "approval_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_call_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_action_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("policy_decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("governance_intent_digest", sa.String(length=64), nullable=False),
        sa.Column("action_snapshot_digest", sa.String(length=64), nullable=True),
        sa.Column("requested_by_principal", sa.String(length=200), nullable=False),
        sa.Column("principal_scope", sa.String(length=200), nullable=False),
        sa.Column("required_approver_role", sa.String(length=100), nullable=False),
        sa.Column("separation_of_duties", sa.Boolean(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "PENDING",
                "APPROVED",
                "DENIED",
                "EXPIRED",
                "CANCELLED",
                name="approval_request_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "length(governance_intent_digest) = 64",
            name="ck_approval_requests_intent_digest_length",
        ),
        sa.CheckConstraint(
            "action_snapshot_digest IS NULL OR length(action_snapshot_digest) = 64",
            name="ck_approval_requests_snapshot_digest_length",
        ),
        sa.CheckConstraint(
            "(external_action_id IS NULL AND action_snapshot_digest IS NULL) OR "
            "(external_action_id IS NOT NULL AND action_snapshot_digest IS NOT NULL)",
            name="ck_approval_requests_action_binding_shape",
        ),
        sa.CheckConstraint(
            "length(btrim(requested_by_principal)) > 0",
            name="ck_approval_requests_nonblank_requester",
        ),
        sa.CheckConstraint(
            "length(btrim(principal_scope)) > 0",
            name="ck_approval_requests_nonblank_scope",
        ),
        sa.CheckConstraint(
            "length(btrim(required_approver_role)) > 0",
            name="ck_approval_requests_nonblank_required_role",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_approval_requests_expiry_after_creation",
        ),
        sa.CheckConstraint(
            "(status = 'PENDING' AND decided_at IS NULL) OR "
            "(status <> 'PENDING' AND decided_at IS NOT NULL)",
            name="ck_approval_requests_status_decided_shape",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["tool_call_id"],
            ["tool_calls.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["external_action_id"],
            ["external_actions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["policy_decision_id"],
            ["policy_decisions.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tool_call_id", name="uq_approval_requests_tool_call"),
        sa.UniqueConstraint(
            "policy_decision_id",
            name="uq_approval_requests_policy_decision",
        ),
        sa.UniqueConstraint(
            "external_action_id",
            name="uq_approval_requests_external_action",
        ),
    )
    op.create_index(
        "uq_approval_requests_one_pending_per_run",
        "approval_requests",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.create_index(
        "ix_approval_requests_scope_status",
        "approval_requests",
        ["principal_scope", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_approval_requests_scope_status",
        table_name="approval_requests",
    )
    op.drop_index(
        "uq_approval_requests_one_pending_per_run",
        table_name="approval_requests",
    )
    op.drop_table("approval_requests")
    postgresql.ENUM(name="approval_request_status").drop(
        op.get_bind(),
        checkfirst=True,
    )

    op.drop_index(
        "uq_external_actions_one_nonterminal_per_run",
        table_name="external_actions",
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

    op.drop_index(
        "uq_tool_calls_one_active_per_run",
        table_name="tool_calls",
    )
    op.create_index(
        "uq_tool_calls_one_active_per_run",
        "tool_calls",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('READY', 'EXECUTING')"),
    )

    op.drop_constraint(
        "ck_runs_nonterminal_has_no_completed_at",
        "runs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_runs_nonterminal_has_no_completed_at",
        "runs",
        "status NOT IN ('CREATED', 'QUEUED', 'RUNNING', 'WAITING_ACTION_RESOLUTION') "
        "OR completed_at IS NULL",
    )

    # PostgreSQL cannot remove a single enum label in place. As in the accepted
    # Stage 3.2 enum-expansion migrations, downgrade restores schema consumers
    # and intentionally leaves the shared enum labels present.
