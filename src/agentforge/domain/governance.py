from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

from .enums import GovernanceDecision, GovernancePolicyStatus, PrincipalType, ToolEffectType

MAX_PRINCIPAL_ID_LENGTH = 200
MAX_PRINCIPAL_SCOPE_LENGTH = 200
MAX_AUTHN_SOURCE_LENGTH = 100
MAX_ROLE_LENGTH = 100
MAX_ROLE_COUNT = 32
MAX_POLICY_KEY_LENGTH = 200
MAX_RULE_ID_LENGTH = 200
MAX_POLICY_RULES = 128
MAX_MATCH_VALUES = 128
MAX_ABS_RULE_PRIORITY = 1_000_000
MAX_APPROVAL_TTL_SECONDS = 30 * 24 * 60 * 60


def _normalized_text(value: str, *, field: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} cannot be blank")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds maximum length {max_length}")
    return normalized


def _normalized_strings(
    values: Iterable[str],
    *,
    field: str,
    max_count: int = MAX_MATCH_VALUES,
    max_length: int = 200,
) -> tuple[str, ...]:
    normalized = tuple(
        sorted({_normalized_text(value, field=field, max_length=max_length) for value in values})
    )
    if len(normalized) > max_count:
        raise ValueError(f"{field} exceeds maximum count {max_count}")
    return normalized


def _normalized_uuids(values: Iterable[UUID], *, field: str) -> tuple[UUID, ...]:
    normalized = tuple(sorted(set(values), key=str))
    if len(normalized) > MAX_MATCH_VALUES:
        raise ValueError(f"{field} exceeds maximum count {MAX_MATCH_VALUES}")
    return normalized


@dataclass(frozen=True, slots=True)
class PrincipalContext:
    principal_id: str
    principal_type: PrincipalType
    roles: tuple[str, ...]
    principal_scope: str
    authn_source: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "principal_id",
            _normalized_text(
                self.principal_id,
                field="principal_id",
                max_length=MAX_PRINCIPAL_ID_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "principal_scope",
            _normalized_text(
                self.principal_scope,
                field="principal_scope",
                max_length=MAX_PRINCIPAL_SCOPE_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "authn_source",
            _normalized_text(
                self.authn_source,
                field="authn_source",
                max_length=MAX_AUTHN_SOURCE_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "roles",
            _normalized_strings(
                self.roles,
                field="role",
                max_count=MAX_ROLE_COUNT,
                max_length=MAX_ROLE_LENGTH,
            ),
        )


@dataclass(frozen=True, slots=True)
class GovernanceApprovalRequirement:
    required_approver_role: str
    separation_of_duties: bool
    ttl_seconds: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "required_approver_role",
            _normalized_text(
                self.required_approver_role,
                field="required_approver_role",
                max_length=MAX_ROLE_LENGTH,
            ),
        )
        if self.ttl_seconds <= 0 or self.ttl_seconds > MAX_APPROVAL_TTL_SECONDS:
            raise ValueError("ttl_seconds is outside the accepted bounded range")

    def to_record(self) -> dict[str, object]:
        return {
            "required_approver_role": self.required_approver_role,
            "separation_of_duties": self.separation_of_duties,
            "ttl_seconds": self.ttl_seconds,
        }

    @classmethod
    def from_record(cls, record: Mapping[str, object]) -> GovernanceApprovalRequirement:
        role = record.get("required_approver_role")
        separation = record.get("separation_of_duties")
        ttl = record.get("ttl_seconds")
        if not isinstance(role, str) or not isinstance(separation, bool) or not isinstance(ttl, int):
            raise ValueError("malformed approval requirement")
        return cls(role, separation, ttl)


@dataclass(frozen=True, slots=True)
class GovernancePolicyRule:
    rule_id: str
    priority: int
    principal_roles_any: tuple[str, ...] = ()
    agent_version_ids: tuple[UUID, ...] = ()
    tool_version_ids: tuple[UUID, ...] = ()
    effect_types: tuple[ToolEffectType, ...] = ()
    principal_scopes: tuple[str, ...] = ()
    decision: GovernanceDecision = GovernanceDecision.DENY
    approval: GovernanceApprovalRequirement | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "rule_id",
            _normalized_text(self.rule_id, field="rule_id", max_length=MAX_RULE_ID_LENGTH),
        )
        if isinstance(self.priority, bool) or abs(self.priority) > MAX_ABS_RULE_PRIORITY:
            raise ValueError("priority is outside the accepted bounded range")
        object.__setattr__(
            self,
            "principal_roles_any",
            _normalized_strings(
                self.principal_roles_any,
                field="principal_role",
                max_length=MAX_ROLE_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "agent_version_ids",
            _normalized_uuids(self.agent_version_ids, field="agent_version_ids"),
        )
        object.__setattr__(
            self,
            "tool_version_ids",
            _normalized_uuids(self.tool_version_ids, field="tool_version_ids"),
        )
        object.__setattr__(
            self,
            "effect_types",
            tuple(sorted(set(self.effect_types), key=lambda item: item.value)),
        )
        object.__setattr__(
            self,
            "principal_scopes",
            _normalized_strings(
                self.principal_scopes,
                field="principal_scope",
                max_length=MAX_PRINCIPAL_SCOPE_LENGTH,
            ),
        )
        if self.decision is GovernanceDecision.REQUIRE_APPROVAL:
            if self.approval is None:
                raise ValueError("REQUIRE_APPROVAL rule requires approval metadata")
        elif self.approval is not None:
            raise ValueError("approval metadata is only valid for REQUIRE_APPROVAL")

    def to_record(self) -> dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "priority": self.priority,
            "principal_roles_any": list(self.principal_roles_any),
            "agent_version_ids": [str(value) for value in self.agent_version_ids],
            "tool_version_ids": [str(value) for value in self.tool_version_ids],
            "effect_types": [value.value for value in self.effect_types],
            "principal_scopes": list(self.principal_scopes),
            "decision": self.decision.value,
            "approval": None if self.approval is None else self.approval.to_record(),
        }

    @classmethod
    def from_record(cls, record: Mapping[str, object]) -> GovernancePolicyRule:
        rule_id = record.get("rule_id")
        priority = record.get("priority")
        decision = record.get("decision")
        if (
            not isinstance(rule_id, str)
            or not isinstance(priority, int)
            or isinstance(priority, bool)
            or not isinstance(decision, str)
        ):
            raise ValueError("malformed governance policy rule")

        def strings(name: str) -> tuple[str, ...]:
            value = record.get(name, [])
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError(f"{name} must be a string list")
            return tuple(cast(str, item) for item in value)

        approval_value = record.get("approval")
        approval: GovernanceApprovalRequirement | None
        if approval_value is None:
            approval = None
        elif isinstance(approval_value, Mapping):
            approval = GovernanceApprovalRequirement.from_record(
                cast(Mapping[str, object], approval_value)
            )
        else:
            raise ValueError("approval must be an object or null")

        return cls(
            rule_id=rule_id,
            priority=priority,
            principal_roles_any=strings("principal_roles_any"),
            agent_version_ids=tuple(UUID(value) for value in strings("agent_version_ids")),
            tool_version_ids=tuple(UUID(value) for value in strings("tool_version_ids")),
            effect_types=tuple(ToolEffectType(value) for value in strings("effect_types")),
            principal_scopes=strings("principal_scopes"),
            decision=GovernanceDecision(decision),
            approval=approval,
        )


def normalize_policy_rules(
    rules: Iterable[GovernancePolicyRule],
) -> tuple[GovernancePolicyRule, ...]:
    normalized = tuple(rules)
    if len(normalized) > MAX_POLICY_RULES:
        raise ValueError(f"policy exceeds maximum rule count {MAX_POLICY_RULES}")
    rule_ids = [rule.rule_id for rule in normalized]
    if len(rule_ids) != len(set(rule_ids)):
        raise ValueError("rule_id must be unique within one policy version")
    return normalized


@dataclass(frozen=True, slots=True)
class GovernancePolicyVersion:
    id: UUID
    policy_key: str
    version_number: int
    status: GovernancePolicyStatus
    rules: tuple[GovernancePolicyRule, ...]
    created_at: datetime
    published_at: datetime | None = None
    retired_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "policy_key",
            _normalized_text(
                self.policy_key,
                field="policy_key",
                max_length=MAX_POLICY_KEY_LENGTH,
            ),
        )
        if self.version_number <= 0:
            raise ValueError("version_number must be positive")
        object.__setattr__(self, "rules", normalize_policy_rules(self.rules))
        if self.status is GovernancePolicyStatus.DRAFT:
            if self.published_at is not None or self.retired_at is not None:
                raise ValueError("DRAFT policy cannot have lifecycle terminal timestamps")
        elif self.status is GovernancePolicyStatus.PUBLISHED:
            if self.published_at is None or self.retired_at is not None:
                raise ValueError("PUBLISHED policy requires published_at only")
        elif self.published_at is None or self.retired_at is None:
            raise ValueError("RETIRED policy requires published_at and retired_at")
