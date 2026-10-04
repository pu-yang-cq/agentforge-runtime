from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}: {old[:100]!r}")
    file.write_text(text.replace(old, new))


# Domain enums.
replace_once(
    "src/agentforge/domain/enums.py",
    '''class ToolEffectType(StrEnum):
    READ = "READ"
''',
    '''class ToolEffectType(StrEnum):
    READ = "READ"
    WRITE = "WRITE"
    EXTERNAL_SIDE_EFFECT = "EXTERNAL_SIDE_EFFECT"
    DESTRUCTIVE = "DESTRUCTIVE"


class ExternalActionStatus(StrEnum):
    READY = "READY"
    EXECUTING = "EXECUTING"
    UNKNOWN = "UNKNOWN"
    RECONCILING = "RECONCILING"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"
''',
)

# Canonical ActionSnapshot V1 and ExternalAction domain values.
Path("src/agentforge/domain/actions.py").write_text(
    '''from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any
from uuid import UUID, uuid4

from agentforge.domain.enums import ExternalActionStatus, ToolEffectType

ACTION_SNAPSHOT_FORMAT_VERSION = 1
MIN_SAFE_INTEGER = -9_007_199_254_740_991
MAX_SAFE_INTEGER = 9_007_199_254_740_991


def _validate_string(value: str) -> None:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("canonical strings must contain Unicode scalar values only") from exc


def _normalize(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        _validate_string(value)
        return value
    if isinstance(value, int):
        if not MIN_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
            raise ValueError("integer is outside the AgentForge canonical safe range")
        return value
    if isinstance(value, float):
        raise ValueError("floating-point values are prohibited in ActionSnapshot V1")
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("canonical object keys must be strings")
            _validate_string(key)
            normalized[key] = _normalize(item)
        # RFC 8785 object-name order uses UTF-16 code units.
        return {
            key: normalized[key]
            for key in sorted(normalized, key=lambda item: item.encode("utf-16-be"))
        }
    raise ValueError(f"unsupported ActionSnapshot V1 value type: {type(value).__name__}")


def canonical_json_v1(value: Any) -> bytes:
    normalized = _normalize(value)
    encoded = json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,
    )
    return encoded.encode("utf-8")


@dataclass(frozen=True, slots=True)
class ActionSnapshot:
    id: UUID
    format_version: int
    operation_id: UUID
    tool_version_id: UUID
    effect_type: ToolEffectType
    credential_ref: str | None
    arguments: dict[str, Any]
    canonical_json: str
    digest: str

    @classmethod
    def create(
        cls,
        *,
        operation_id: UUID,
        tool_version_id: UUID,
        effect_type: ToolEffectType,
        arguments: dict[str, Any],
        credential_ref: str | None,
    ) -> ActionSnapshot:
        if credential_ref is not None:
            _validate_string(credential_ref)
        payload = {
            "arguments": arguments,
            "credential_ref": credential_ref,
            "effect_type": effect_type.value,
            "format_version": ACTION_SNAPSHOT_FORMAT_VERSION,
            "operation_id": str(operation_id),
            "tool_version_id": str(tool_version_id),
        }
        canonical = canonical_json_v1(payload)
        return cls(
            id=uuid4(),
            format_version=ACTION_SNAPSHOT_FORMAT_VERSION,
            operation_id=operation_id,
            tool_version_id=tool_version_id,
            effect_type=effect_type,
            credential_ref=credential_ref,
            arguments=_normalize(arguments),
            canonical_json=canonical.decode("utf-8"),
            digest=sha256(canonical).hexdigest(),
        )


@dataclass(slots=True)
class ExternalAction:
    id: UUID
    run_id: UUID
    tool_call_id: UUID
    action_snapshot_id: UUID
    operation_id: UUID
    status: ExternalActionStatus = ExternalActionStatus.READY
    current_attempt_id: UUID | None = None

    @classmethod
    def create(
        cls,
        *,
        run_id: UUID,
        tool_call_id: UUID,
        action_snapshot_id: UUID,
        operation_id: UUID,
    ) -> ExternalAction:
        return cls(
            id=uuid4(),
            run_id=run_id,
            tool_call_id=tool_call_id,
            action_snapshot_id=action_snapshot_id,
            operation_id=operation_id,
        )
'''
)

# ORM enums import.
replace_once(
    "src/agentforge/infrastructure/db/models.py",
    '''from agentforge.domain.enums import (
    QueueReason,
''',
    '''from agentforge.domain.enums import (
    ExternalActionStatus,
    QueueReason,
''',
)

# Insert ActionSnapshot + ExternalAction before ToolExecutionAttempt so metadata
# exposes intent tables next to execution facts.
replace_once(
    "src/agentforge/infrastructure/db/models.py",
    '''class ToolExecutionAttemptRow(Base):
''',
    '''class ActionSnapshotRow(Base):
    __tablename__ = "action_snapshots"
    __table_args__ = (
        CheckConstraint("format_version = 1", name="ck_action_snapshots_format_v1"),
        UniqueConstraint("operation_id", name="uq_action_snapshots_operation_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    format_version: Mapped[int] = mapped_column(Integer, nullable=False)
    operation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    tool_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("tool_versions.id", ondelete="RESTRICT"), nullable=False
    )
    effect_type: Mapped[ToolEffectType] = mapped_column(
        Enum(ToolEffectType, name="tool_effect_type", create_type=False), nullable=False
    )
    credential_ref: Mapped[str | None] = mapped_column(String(300))
    arguments: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    canonical_json: Mapped[str] = mapped_column(Text, nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class ExternalActionRow(Base):
    __tablename__ = "external_actions"
    __table_args__ = (
        UniqueConstraint("operation_id", name="uq_external_actions_operation_id"),
        UniqueConstraint("tool_call_id", name="uq_external_actions_tool_call_id"),
        UniqueConstraint("action_snapshot_id", name="uq_external_actions_snapshot_id"),
        CheckConstraint(
            "(status = 'EXECUTING' AND current_attempt_id IS NOT NULL) OR "
            "(status <> 'EXECUTING' AND current_attempt_id IS NULL)",
            name="ck_external_actions_current_attempt_shape",
        ),
        Index(
            "uq_external_actions_one_nonterminal_per_run",
            "run_id",
            unique=True,
            postgresql_where=text(
                "status IN ('READY', 'EXECUTING', 'UNKNOWN', 'RECONCILING', 'MANUAL_REVIEW')"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="RESTRICT"), nullable=False
    )
    tool_call_id: Mapped[UUID] = mapped_column(
        ForeignKey("tool_calls.id", ondelete="RESTRICT"), nullable=False
    )
    action_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("action_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    operation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    status: Mapped[ExternalActionStatus] = mapped_column(
        Enum(ExternalActionStatus, name="external_action_status"), nullable=False
    )
    current_attempt_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "tool_execution_attempts.id",
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_external_actions_current_attempt",
        )
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class ToolExecutionAttemptRow(Base):
''',
)

# Turn the already-reserved external_action_id into a real FK.
replace_once(
    "src/agentforge/infrastructure/db/models.py",
    '''    external_action_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
''',
    '''    external_action_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "external_actions.id",
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_tool_execution_attempts_external_action",
        )
    )
''',
)

# Migration 0009.
Path("migrations/versions/0009_external_action_intent.py").write_text(
    '''"""add ActionSnapshot V1 and ExternalAction durable intent

Revision ID: 0009_external_action_intent
Revises: 0008_read_retry_policy
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_external_action_intent"
down_revision: str | None = "0008_read_retry_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE tool_effect_type ADD VALUE IF NOT EXISTS 'WRITE'")
    op.execute(
        "ALTER TYPE tool_effect_type ADD VALUE IF NOT EXISTS 'EXTERNAL_SIDE_EFFECT'"
    )
    op.execute("ALTER TYPE tool_effect_type ADD VALUE IF NOT EXISTS 'DESTRUCTIVE'")

    action_status = postgresql.ENUM(
        "READY",
        "EXECUTING",
        "UNKNOWN",
        "RECONCILING",
        "MANUAL_REVIEW",
        "SUCCEEDED",
        "FAILED",
        "ABORTED",
        name="external_action_status",
    )
    action_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "action_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("format_version", sa.Integer(), nullable=False),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "tool_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tool_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
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
        sa.Column("credential_ref", sa.String(length=300), nullable=True),
        sa.Column("arguments", postgresql.JSONB(), nullable=False),
        sa.Column("canonical_json", sa.Text(), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("format_version = 1", name="ck_action_snapshots_format_v1"),
        sa.UniqueConstraint("operation_id", name="uq_action_snapshots_operation_id"),
    )

    op.create_table(
        "external_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "tool_call_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tool_calls.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "action_snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("action_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "READY",
                "EXECUTING",
                "UNKNOWN",
                "RECONCILING",
                "MANUAL_REVIEW",
                "SUCCEEDED",
                "FAILED",
                "ABORTED",
                name="external_action_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("current_attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("operation_id", name="uq_external_actions_operation_id"),
        sa.UniqueConstraint("tool_call_id", name="uq_external_actions_tool_call_id"),
        sa.UniqueConstraint("action_snapshot_id", name="uq_external_actions_snapshot_id"),
        sa.CheckConstraint(
            "(status = 'EXECUTING' AND current_attempt_id IS NOT NULL) OR "
            "(status <> 'EXECUTING' AND current_attempt_id IS NULL)",
            name="ck_external_actions_current_attempt_shape",
        ),
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
    op.create_foreign_key(
        "fk_external_actions_current_attempt",
        "external_actions",
        "tool_execution_attempts",
        ["current_attempt_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_tool_execution_attempts_external_action",
        "tool_execution_attempts",
        "external_actions",
        ["external_action_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_tool_execution_attempts_external_action",
        "tool_execution_attempts",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_external_actions_current_attempt",
        "external_actions",
        type_="foreignkey",
    )
    op.drop_index(
        "uq_external_actions_one_nonterminal_per_run",
        table_name="external_actions",
    )
    op.drop_table("external_actions")
    op.drop_table("action_snapshots")
    postgresql.ENUM(name="external_action_status").drop(op.get_bind(), checkfirst=True)
'''
)

# Golden-vector and domain tests.
Path("tests/unit/test_action_snapshot_v1.py").write_text(
    '''from uuid import UUID, uuid4

import pytest

from agentforge.domain.actions import (
    MAX_SAFE_INTEGER,
    ActionSnapshot,
    ExternalAction,
    canonical_json_v1,
)
from agentforge.domain.enums import ExternalActionStatus, ToolEffectType


def test_action_snapshot_v1_golden_bytes_and_digest() -> None:
    snapshot = ActionSnapshot.create(
        operation_id=UUID("123e4567-e89b-12d3-a456-426614174000"),
        tool_version_id=UUID("123e4567-e89b-12d3-a456-426614174001"),
        effect_type=ToolEffectType.EXTERNAL_SIDE_EFFECT,
        credential_ref="cred:crm-prod",
        arguments={
            "customer_id": "c-123",
            "count": 2,
            "flags": [True, None, "x"],
        },
    )
    expected = (
        '{"arguments":{"count":2,"customer_id":"c-123","flags":[true,null,"x"]},'
        '"credential_ref":"cred:crm-prod","effect_type":"EXTERNAL_SIDE_EFFECT",'
        '"format_version":1,"operation_id":"123e4567-e89b-12d3-a456-426614174000",'
        '"tool_version_id":"123e4567-e89b-12d3-a456-426614174001"}'
    )
    assert snapshot.canonical_json == expected
    assert snapshot.digest == "c596747972eee80b08adabeb1cb519e174ef74297e455ff854488afb3242e89f"


def test_action_snapshot_v1_rejects_float_unsafe_integer_and_non_string_key() -> None:
    with pytest.raises(ValueError, match="floating-point"):
        canonical_json_v1({"amount": 1.5})
    with pytest.raises(ValueError, match="safe range"):
        canonical_json_v1({"amount": MAX_SAFE_INTEGER + 1})
    with pytest.raises(ValueError, match="keys must be strings"):
        canonical_json_v1({1: "no"})


def test_action_snapshot_v1_uses_utf16_member_order() -> None:
    # U+10000 sorts before U+E000 by UTF-16 code units although its scalar
    # value is larger. This guards the RFC 8785 member-order rule.
    encoded = canonical_json_v1({"\ue000": 1, "\U00010000": 2}).decode("utf-8")
    assert encoded == '{"𐀀":2,"":1}'


def test_external_action_starts_ready_with_stable_operation_identity() -> None:
    operation_id = uuid4()
    action = ExternalAction.create(
        run_id=uuid4(),
        tool_call_id=uuid4(),
        action_snapshot_id=uuid4(),
        operation_id=operation_id,
    )
    assert action.operation_id == operation_id
    assert action.status is ExternalActionStatus.READY
    assert action.current_attempt_id is None
'''
)

# Migration contracts.
replace_once(
    "tests/unit/test_migration_contract.py",
    '''    assert "CK_TOOL_VERSIONS_POSITIVE_READ_RETRY_ATTEMPTS" in ddl
''',
    '''    assert "CK_TOOL_VERSIONS_POSITIVE_READ_RETRY_ATTEMPTS" in ddl
    assert "0009_EXTERNAL_ACTION_INTENT" in ddl
    assert "CREATE TABLE ACTION_SNAPSHOTS" in ddl
    assert "CREATE TABLE EXTERNAL_ACTIONS" in ddl
    assert "UQ_EXTERNAL_ACTIONS_ONE_NONTERMINAL_PER_RUN" in ddl
    assert "FK_TOOL_EXECUTION_ATTEMPTS_EXTERNAL_ACTION" in ddl
''',
)

# Schema contracts.
replace_once(
    "tests/unit/test_postgres_contracts.py",
    '''        "tool_execution_attempts",
        "domain_events",
''',
    '''        "tool_execution_attempts",
        "action_snapshots",
        "external_actions",
        "domain_events",
''',
)

replace_once(
    "tests/unit/test_postgres_contracts.py",
    '''def test_run_schema_enforces_terminal_row_shape() -> None:
''',
    '''def test_external_action_schema_enforces_intent_invariants() -> None:
    snapshots = Base.metadata.tables["action_snapshots"]
    assert {
        "format_version",
        "operation_id",
        "tool_version_id",
        "effect_type",
        "credential_ref",
        "arguments",
        "canonical_json",
        "digest",
    }.issubset(snapshots.c.keys())

    actions = Base.metadata.tables["external_actions"]
    assert {
        "run_id",
        "tool_call_id",
        "action_snapshot_id",
        "operation_id",
        "status",
        "current_attempt_id",
    }.issubset(actions.c.keys())

    indexes = {index.name: index for index in actions.indexes}
    active = indexes["uq_external_actions_one_nonterminal_per_run"]
    assert active.unique is True
    assert [column.name for column in active.columns] == ["run_id"]
    where = str(active.dialect_options["postgresql"]["where"]).upper()
    assert "READY" in where
    assert "EXECUTING" in where
    assert "UNKNOWN" in where
    assert "RECONCILING" in where
    assert "MANUAL_REVIEW" in where

    action_uniques = {
        constraint.name
        for constraint in actions.constraints
        if constraint.name is not None
    }
    assert {
        "uq_external_actions_operation_id",
        "uq_external_actions_tool_call_id",
        "uq_external_actions_snapshot_id",
        "ck_external_actions_current_attempt_shape",
    }.issubset(action_uniques)

    attempts = Base.metadata.tables["tool_execution_attempts"]
    assert len(attempts.c.external_action_id.foreign_keys) == 1
    assert len(actions.c.current_attempt_id.foreign_keys) == 1


def test_run_schema_enforces_terminal_row_shape() -> None:
''',
)

Path("tests/unit/test_stage32_b1_migration_contract.py").write_text(
    '''from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_stage32_b1_migration_is_forward_only_from_read_retry_head() -> None:
    migration = (
        ROOT / "migrations" / "versions" / "0009_external_action_intent.py"
    ).read_text()
    assert 'revision: str = "0009_external_action_intent"' in migration
    assert 'down_revision: str | None = "0008_read_retry_policy"' in migration
    assert "action_snapshots" in migration
    assert "external_actions" in migration
    assert "uq_external_actions_one_nonterminal_per_run" in migration
    assert "fk_tool_execution_attempts_external_action" in migration
'''
)
