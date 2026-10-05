from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentforge.application.ports import GovernancePolicyStore
from agentforge.domain.enums import GovernancePolicyStatus
from agentforge.domain.governance import (
    GovernancePolicyRule,
    GovernancePolicyVersion,
    normalize_policy_rules,
)
from agentforge.infrastructure.db.models import GovernancePolicyVersionRow


def _from_row(row: GovernancePolicyVersionRow) -> GovernancePolicyVersion:
    return GovernancePolicyVersion(
        id=row.id,
        policy_key=row.policy_key,
        version_number=row.version_number,
        status=row.status,
        rules=tuple(GovernancePolicyRule.from_record(record) for record in row.rules),
        created_at=row.created_at,
        published_at=row.published_at,
        retired_at=row.retired_at,
    )


class PostgresGovernancePolicyStore(GovernancePolicyStore):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def create_draft(
        self,
        *,
        policy_key: str,
        version_number: int,
        rules: tuple[GovernancePolicyRule, ...],
    ) -> GovernancePolicyVersion:
        normalized_rules = normalize_policy_rules(rules)
        normalized_key = policy_key.strip()
        if not normalized_key:
            raise ValueError("policy_key cannot be blank")
        if len(normalized_key) > 200:
            raise ValueError("policy_key exceeds maximum length 200")
        if version_number <= 0:
            raise ValueError("version_number must be positive")
        async with self._sessions() as session, session.begin():
            row = GovernancePolicyVersionRow(
                id=uuid4(),
                policy_key=normalized_key,
                version_number=version_number,
                status=GovernancePolicyStatus.DRAFT,
                rules=[rule.to_record() for rule in normalized_rules],
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return _from_row(row)

    async def update_draft(
        self,
        policy_version_id: UUID,
        *,
        rules: tuple[GovernancePolicyRule, ...],
    ) -> GovernancePolicyVersion:
        normalized_rules = normalize_policy_rules(rules)
        async with self._sessions() as session, session.begin():
            row = (
                await session.execute(
                    select(GovernancePolicyVersionRow)
                    .where(GovernancePolicyVersionRow.id == policy_version_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if row is None:
                raise KeyError(f"governance policy not found: {policy_version_id}")
            if row.status is not GovernancePolicyStatus.DRAFT:
                raise ValueError("only DRAFT governance policy content may be edited")
            row.rules = [rule.to_record() for rule in normalized_rules]
            row.updated_at = func.clock_timestamp()
            await session.flush()
            await session.refresh(row)
            return _from_row(row)

    async def publish(self, policy_version_id: UUID) -> GovernancePolicyVersion:
        async with self._sessions() as session, session.begin():
            row = (
                await session.execute(
                    select(GovernancePolicyVersionRow)
                    .where(GovernancePolicyVersionRow.id == policy_version_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if row is None:
                raise KeyError(f"governance policy not found: {policy_version_id}")
            if row.status is not GovernancePolicyStatus.DRAFT:
                raise ValueError("only DRAFT governance policy may be published")
            tuple(GovernancePolicyRule.from_record(record) for record in row.rules)
            row.status = GovernancePolicyStatus.PUBLISHED
            row.published_at = func.clock_timestamp()
            row.updated_at = func.clock_timestamp()
            await session.flush()
            await session.refresh(row)
            return _from_row(row)

    async def retire(self, policy_version_id: UUID) -> GovernancePolicyVersion:
        async with self._sessions() as session, session.begin():
            row = (
                await session.execute(
                    select(GovernancePolicyVersionRow)
                    .where(GovernancePolicyVersionRow.id == policy_version_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if row is None:
                raise KeyError(f"governance policy not found: {policy_version_id}")
            if row.status is not GovernancePolicyStatus.PUBLISHED:
                raise ValueError("only PUBLISHED governance policy may be retired")
            row.status = GovernancePolicyStatus.RETIRED
            row.retired_at = func.clock_timestamp()
            row.updated_at = func.clock_timestamp()
            await session.flush()
            await session.refresh(row)
            return _from_row(row)

    async def get(self, policy_version_id: UUID) -> GovernancePolicyVersion | None:
        async with self._sessions() as session:
            row = await session.get(GovernancePolicyVersionRow, policy_version_id)
            return None if row is None else _from_row(row)
