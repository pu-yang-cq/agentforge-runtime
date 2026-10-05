"""add Stage 3.3-A2 governance intent and policy decision audit facts

Revision ID: 0018_governance_decision
Revises: 0017_governance_identity_policy
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_governance_decision"
down_revision: str | None = "0017_governance_identity_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    governance_decision = postgresql.ENUM(
        "ALLOW",
        "DENY",
        "REQUIRE_APPROVAL",
        name="governance_decision",
    )
    governance_decision.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "governance_intents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("format_version", sa.Integer(), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_version_id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.Column("requester_principal_id", sa.String(length=200), nullable=False),
        sa.Column(
            "requester_principal_type",
            postgresql.ENUM(
                "USER",
                "SERVICE",
                name="principal_type",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "requester_roles",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("principal_scope", sa.String(length=200), nullable=False),
        sa.Column("canonical_json", sa.Text(), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("format_version = 1", name="ck_governance_intents_format_v1"),
        sa.CheckConstraint(
            "jsonb_typeof(requester_roles) = 'array'",
            name="ck_governance_intents_roles_array",
        ),
        sa.CheckConstraint(
            "length(digest) = 64",
            name="ck_governance_intents_digest_length",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["agent_version_id"],
            ["agent_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["tool_proposals.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tool_version_id"],
            ["tool_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("proposal_id", name="uq_governance_intents_proposal"),
    )

    op.create_table(
        "policy_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("governance_intent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requester_principal_id", sa.String(length=200), nullable=False),
        sa.Column("principal_scope", sa.String(length=200), nullable=False),
        sa.Column(
            "effective_decision",
            postgresql.ENUM(
                "ALLOW",
                "DENY",
                "REQUIRE_APPROVAL",
                name="governance_decision",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("matched_rule_id", sa.String(length=200), nullable=True),
        sa.Column("intent_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "length(intent_digest) = 64",
            name="ck_policy_decisions_digest_length",
        ),
        sa.ForeignKeyConstraint(
            ["governance_intent_id"],
            ["governance_intents.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["tool_proposals.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tool_version_id"],
            ["tool_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["policy_version_id"],
            ["governance_policy_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("proposal_id", name="uq_policy_decisions_proposal"),
        sa.UniqueConstraint(
            "governance_intent_id",
            name="uq_policy_decisions_intent",
        ),
    )

    op.execute(
        """
        CREATE FUNCTION reject_governance_audit_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          RAISE EXCEPTION 'governance audit facts are immutable';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_governance_intents_immutable
        BEFORE UPDATE OR DELETE ON governance_intents
        FOR EACH ROW EXECUTE FUNCTION reject_governance_audit_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_policy_decisions_immutable
        BEFORE UPDATE OR DELETE ON policy_decisions
        FOR EACH ROW EXECUTE FUNCTION reject_governance_audit_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_policy_decisions_immutable ON policy_decisions")
    op.execute("DROP TRIGGER IF EXISTS trg_governance_intents_immutable ON governance_intents")
    op.execute("DROP FUNCTION IF EXISTS reject_governance_audit_mutation()")
    op.drop_table("policy_decisions")
    op.drop_table("governance_intents")
    postgresql.ENUM(name="governance_decision").drop(op.get_bind(), checkfirst=True)
