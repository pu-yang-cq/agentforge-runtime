"""add Stage 3.3-A1 governance identity and policy foundation

Revision ID: 0017_governance_identity_policy
Revises: 0016_checkpoint_overlay
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_governance_identity_policy"
down_revision: str | None = "0016_checkpoint_overlay"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    governance_mode = postgresql.ENUM(
        "LEGACY_STAGE32",
        "GOVERNED",
        name="governance_mode",
    )
    principal_type = postgresql.ENUM("USER", "SERVICE", name="principal_type")
    policy_status = postgresql.ENUM(
        "DRAFT",
        "PUBLISHED",
        "RETIRED",
        name="governance_policy_status",
    )
    governance_mode.create(op.get_bind(), checkfirst=True)
    principal_type.create(op.get_bind(), checkfirst=True)
    policy_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "governance_policy_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("policy_key", sa.String(length=200), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "DRAFT",
                "PUBLISHED",
                "RETIRED",
                name="governance_policy_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("policy_key", "version_number"),
        sa.CheckConstraint(
            "version_number > 0",
            name="ck_governance_policy_versions_positive_version",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(rules) = 'array' AND jsonb_array_length(rules) <= 128",
            name="ck_governance_policy_versions_bounded_rules",
        ),
        sa.CheckConstraint(
            "(status = 'DRAFT' AND published_at IS NULL AND retired_at IS NULL) OR "
            "(status = 'PUBLISHED' AND published_at IS NOT NULL AND retired_at IS NULL) OR "
            "(status = 'RETIRED' AND published_at IS NOT NULL AND retired_at IS NOT NULL)",
            name="ck_governance_policy_versions_lifecycle_shape",
        ),
    )

    op.add_column(
        "agent_versions",
        sa.Column(
            "governance_mode",
            postgresql.ENUM(
                "LEGACY_STAGE32",
                "GOVERNED",
                name="governance_mode",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'LEGACY_STAGE32'"),
        ),
    )
    op.add_column(
        "agent_versions",
        sa.Column("policy_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_agent_versions_policy_version",
        "agent_versions",
        "governance_policy_versions",
        ["policy_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_agent_versions_governance_shape",
        "agent_versions",
        "(governance_mode = 'LEGACY_STAGE32' AND policy_version_id IS NULL) OR "
        "(governance_mode = 'GOVERNED' AND policy_version_id IS NOT NULL)",
    )

    op.add_column(
        "runs",
        sa.Column("policy_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("requester_principal_id", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column(
            "requester_principal_type",
            postgresql.ENUM(
                "USER",
                "SERVICE",
                name="principal_type",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "runs",
        sa.Column("requester_roles", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("requester_scope", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "runs",
        sa.Column("requester_authn_source", sa.String(length=100), nullable=True),
    )
    op.create_foreign_key(
        "fk_runs_policy_version",
        "runs",
        "governance_policy_versions",
        ["policy_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_runs_governance_snapshot_shape",
        "runs",
        "(policy_version_id IS NULL AND requester_principal_id IS NULL AND "
        "requester_principal_type IS NULL AND requester_roles IS NULL AND "
        "requester_scope IS NULL AND requester_authn_source IS NULL) OR "
        "(policy_version_id IS NOT NULL AND requester_principal_id IS NOT NULL AND "
        "requester_principal_type IS NOT NULL AND requester_roles IS NOT NULL AND "
        "requester_scope IS NOT NULL AND requester_authn_source IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_runs_requester_roles_array",
        "runs",
        "requester_roles IS NULL OR jsonb_typeof(requester_roles) = 'array'",
    )

    op.execute(
        """
        CREATE FUNCTION guard_governance_policy_version_update()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
          IF OLD.status = 'DRAFT' THEN
            IF NEW.status NOT IN ('DRAFT', 'PUBLISHED') THEN
              RAISE EXCEPTION 'invalid governance policy lifecycle transition';
            END IF;
          ELSIF OLD.status = 'PUBLISHED' THEN
            IF NEW.status NOT IN ('PUBLISHED', 'RETIRED') THEN
              RAISE EXCEPTION 'invalid governance policy lifecycle transition';
            END IF;
            IF NEW.policy_key IS DISTINCT FROM OLD.policy_key
               OR NEW.version_number IS DISTINCT FROM OLD.version_number
               OR NEW.rules IS DISTINCT FROM OLD.rules THEN
              RAISE EXCEPTION 'published governance policy content is immutable';
            END IF;
          ELSE
            IF NEW IS DISTINCT FROM OLD THEN
              RAISE EXCEPTION 'retired governance policy is immutable';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_governance_policy_version_update
        BEFORE UPDATE ON governance_policy_versions
        FOR EACH ROW EXECUTE FUNCTION guard_governance_policy_version_update();
        """
    )
    op.execute(
        """
        CREATE FUNCTION guard_agent_version_governance()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
          pinned_status governance_policy_status;
        BEGIN
          IF TG_OP = 'UPDATE' THEN
            IF NEW.governance_mode IS DISTINCT FROM OLD.governance_mode
               OR NEW.policy_version_id IS DISTINCT FROM OLD.policy_version_id THEN
              RAISE EXCEPTION 'AgentVersion governance assignment is immutable';
            END IF;
            RETURN NEW;
          END IF;

          IF NEW.governance_mode = 'GOVERNED' THEN
            SELECT status INTO pinned_status
            FROM governance_policy_versions
            WHERE id = NEW.policy_version_id;
            IF pinned_status IS DISTINCT FROM 'PUBLISHED'::governance_policy_status THEN
              RAISE EXCEPTION 'GOVERNED AgentVersion requires a PUBLISHED policy version';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_agent_version_governance
        BEFORE INSERT OR UPDATE ON agent_versions
        FOR EACH ROW EXECUTE FUNCTION guard_agent_version_governance();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_agent_version_governance ON agent_versions")
    op.execute("DROP FUNCTION IF EXISTS guard_agent_version_governance()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_governance_policy_version_update "
        "ON governance_policy_versions"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_governance_policy_version_update()")

    op.drop_constraint("ck_runs_requester_roles_array", "runs", type_="check")
    op.drop_constraint("ck_runs_governance_snapshot_shape", "runs", type_="check")
    op.drop_constraint("fk_runs_policy_version", "runs", type_="foreignkey")
    op.drop_column("runs", "requester_authn_source")
    op.drop_column("runs", "requester_scope")
    op.drop_column("runs", "requester_roles")
    op.drop_column("runs", "requester_principal_type")
    op.drop_column("runs", "requester_principal_id")
    op.drop_column("runs", "policy_version_id")

    op.drop_constraint("ck_agent_versions_governance_shape", "agent_versions", type_="check")
    op.drop_constraint("fk_agent_versions_policy_version", "agent_versions", type_="foreignkey")
    op.drop_column("agent_versions", "policy_version_id")
    op.drop_column("agent_versions", "governance_mode")

    op.drop_table("governance_policy_versions")
    postgresql.ENUM(name="governance_policy_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="principal_type").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="governance_mode").drop(op.get_bind(), checkfirst=True)
