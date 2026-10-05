# ruff: noqa: E402

import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

REQUIRE_POSTGRES = os.getenv("AGENTFORGE_REQUIRE_POSTGRES_INTEGRATION") == "1"
try:
    import psycopg  # noqa: F401
except ImportError as exc:
    if REQUIRE_POSTGRES:
        raise RuntimeError("psycopg is required for Stage 3.3-A1 acceptance") from exc
    pytest.skip("psycopg is not installed", allow_module_level=True)

DATABASE_URL = os.getenv("AGENTFORGE_TEST_DATABASE_URL")
if not DATABASE_URL:
    if REQUIRE_POSTGRES:
        raise RuntimeError("AGENTFORGE_TEST_DATABASE_URL is required for Stage 3.3-A1 acceptance")
    pytest.skip("set AGENTFORGE_TEST_DATABASE_URL", allow_module_level=True)

from agentforge.domain.enums import (
    GovernanceDecision,
    GovernanceMode,
    GovernancePolicyStatus,
    PrincipalType,
)
from agentforge.domain.governance import GovernancePolicyRule, PrincipalContext
from agentforge.infrastructure.db.governance_store import PostgresGovernancePolicyStore
from agentforge.infrastructure.db.models import AgentRow, AgentVersionRow, RunRow
from agentforge.infrastructure.db.runtime_store import PostgresRuntimeStore
from agentforge.infrastructure.db.session import create_engine, create_session_factory


def _config() -> Config:
    config = Config("alembic.ini")
    config.attributes["agentforge_explicit_database_url"] = DATABASE_URL
    config.set_main_option("sqlalchemy.url", DATABASE_URL)
    return config


def _reset_head() -> None:
    config = _config()
    command.downgrade(config, "base")
    command.upgrade(config, "head")


@pytest.mark.asyncio
async def test_a1_forward_migration_backfills_existing_agent_versions_exactly_legacy() -> None:
    config = _config()
    command.downgrade(config, "base")
    command.upgrade(config, "0016_checkpoint_overlay")

    engine = create_engine(DATABASE_URL)
    agent_id = uuid4()
    version_id = uuid4()
    async with engine.begin() as connection:
        await connection.execute(
            text("INSERT INTO agents (id, name, description) VALUES (:id, :name, '')"),
            {"id": agent_id, "name": f"legacy-{agent_id}"},
        )
        await connection.execute(
            text(
                "INSERT INTO agent_versions (id, agent_id, version_number, instructions) "
                "VALUES (:id, :agent_id, 1, 'legacy accepted runtime')"
            ),
            {"id": version_id, "agent_id": agent_id},
        )
    await engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine(DATABASE_URL)
    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT governance_mode::text, policy_version_id "
                    "FROM agent_versions WHERE id = :id"
                ),
                {"id": version_id},
            )
        ).one()
    assert row[0] == "LEGACY_STAGE32"
    assert row[1] is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_a1_policy_lifecycle_agent_version_pin_and_immutability() -> None:
    _reset_head()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    policy_store = PostgresGovernancePolicyStore(sessions)
    rule = GovernancePolicyRule(
        rule_id="default-deny",
        priority=0,
        decision=GovernanceDecision.DENY,
    )
    draft = await policy_store.create_draft(
        policy_key="tenant-a-runtime",
        version_number=1,
        rules=(rule,),
    )
    assert draft.status is GovernancePolicyStatus.DRAFT

    agent_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(AgentRow(id=agent_id, name=f"governed-{agent_id}", description=""))

    async with sessions() as session:
        session.add(
            AgentVersionRow(
                id=uuid4(),
                agent_id=agent_id,
                version_number=1,
                instructions="must fail because policy is draft",
                governance_mode=GovernanceMode.GOVERNED,
                policy_version_id=draft.id,
            )
        )
        with pytest.raises(DBAPIError):
            await session.commit()
        await session.rollback()

    published = await policy_store.publish(draft.id)
    assert published.status is GovernancePolicyStatus.PUBLISHED

    version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            AgentVersionRow(
                id=version_id,
                agent_id=agent_id,
                version_number=2,
                instructions="pinned governed version",
                governance_mode=GovernanceMode.GOVERNED,
                policy_version_id=published.id,
            )
        )

    async with sessions() as session:
        with pytest.raises(DBAPIError):
            await session.execute(
                text("UPDATE agent_versions SET policy_version_id = NULL WHERE id = :id"),
                {"id": version_id},
            )
            await session.commit()
        await session.rollback()

    async with sessions() as session:
        with pytest.raises(DBAPIError):
            await session.execute(
                text("UPDATE governance_policy_versions SET rules = '[]'::jsonb WHERE id = :id"),
                {"id": published.id},
            )
            await session.commit()
        await session.rollback()

    retired = await policy_store.retire(published.id)
    assert retired.status is GovernancePolicyStatus.RETIRED

    async with sessions() as session:
        session.add(
            AgentVersionRow(
                id=uuid4(),
                agent_id=agent_id,
                version_number=3,
                instructions="retired policy cannot be newly assigned",
                governance_mode=GovernanceMode.GOVERNED,
                policy_version_id=retired.id,
            )
        )
        with pytest.raises(DBAPIError):
            await session.commit()
        await session.rollback()

    async with sessions() as session:
        existing = await session.get(AgentVersionRow, version_id)
        assert existing is not None
        assert existing.policy_version_id == retired.id

    await engine.dispose()


@pytest.mark.asyncio
async def test_a1_legacy_run_preserves_sql_null_governance_snapshot() -> None:
    _reset_head()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)

    agent_id = uuid4()
    version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(AgentRow(id=agent_id, name=f"legacy-run-{agent_id}", description=""))
        await session.flush()
        session.add(
            AgentVersionRow(
                id=version_id,
                agent_id=agent_id,
                version_number=1,
                instructions="legacy Stage 3.2 compatibility",
            )
        )

    store = PostgresRuntimeStore(sessions)
    run = await store.create_run(
        agent_version_id=version_id,
        input_text="legacy compatibility",
        idempotency_key="legacy-a1-compatibility",
        principal_scope="legacy-user",
    )

    assert run.policy_version_id is None
    assert run.requester_principal_id is None
    assert run.requester_principal_type is None
    assert run.requester_roles is None
    assert run.requester_scope is None
    assert run.requester_authn_source is None

    async with sessions() as session:
        durable = await session.get(RunRow, run.id)
        assert durable is not None
        assert durable.requester_roles is None
        roles_is_sql_null = await session.scalar(
            text("SELECT requester_roles IS NULL FROM runs WHERE id = :run_id"),
            {"run_id": run.id},
        )
        assert roles_is_sql_null is True

    await engine.dispose()


@pytest.mark.asyncio
async def test_a1_governed_run_pins_policy_and_normalized_requester_snapshot() -> None:
    _reset_head()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    policy_store = PostgresGovernancePolicyStore(sessions)
    draft = await policy_store.create_draft(
        policy_key="snapshot-policy",
        version_number=1,
        rules=(
            GovernancePolicyRule(
                rule_id="deny-until-a2",
                priority=0,
                decision=GovernanceDecision.DENY,
            ),
        ),
    )
    published = await policy_store.publish(draft.id)

    agent_id = uuid4()
    version_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(AgentRow(id=agent_id, name=f"snapshot-{agent_id}", description=""))
        await session.flush()
        session.add(
            AgentVersionRow(
                id=version_id,
                agent_id=agent_id,
                version_number=1,
                instructions="identity foundation only",
                governance_mode=GovernanceMode.GOVERNED,
                policy_version_id=published.id,
            )
        )

    store = PostgresRuntimeStore(sessions)
    with pytest.raises(ValueError):
        await store.create_run(
            agent_version_id=version_id,
            input_text="governed without trusted principal",
            idempotency_key="missing-principal",
            principal_scope="body-supplied-scope",
        )

    principal = PrincipalContext(
        principal_id=" user-9 ",
        principal_type=PrincipalType.USER,
        roles=(" runtime:run:create ", "operator", "operator"),
        principal_scope=" tenant-a ",
        authn_source=" oidc ",
    )
    run = await store.create_run(
        agent_version_id=version_id,
        input_text="governed snapshot",
        idempotency_key="governed-create",
        principal_scope="untrusted-body-scope",
        principal=principal,
    )
    assert run.policy_version_id == published.id
    assert run.requester_principal_id == "user-9"
    assert run.requester_roles == ("operator", "runtime:run:create")
    assert run.requester_scope == "tenant-a"
    assert run.requester_authn_source == "oidc"

    loaded_version = await store.load_agent_version(version_id)
    assert loaded_version.governance_mode is GovernanceMode.GOVERNED
    assert loaded_version.policy_version_id == published.id

    async with sessions() as session:
        durable = await session.get(RunRow, run.id)
        assert durable is not None
        assert durable.policy_version_id == published.id
        assert durable.requester_scope == "tenant-a"
        scope = await session.scalar(
            text("SELECT principal_scope FROM idempotency_records WHERE resource_id = :run_id"),
            {"run_id": run.id},
        )
        assert scope == "tenant-a"

    await engine.dispose()
