# ruff: noqa: E402

import json
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

REQUIRE_POSTGRES = os.getenv("AGENTFORGE_REQUIRE_POSTGRES_INTEGRATION") == "1"
try:
    import psycopg  # noqa: F401
except ImportError as exc:
    if REQUIRE_POSTGRES:
        raise RuntimeError("psycopg is required for Stage 3.3-A2 acceptance") from exc
    pytest.skip("psycopg is not installed", allow_module_level=True)

DATABASE_URL = os.getenv("AGENTFORGE_TEST_DATABASE_URL")
if not DATABASE_URL:
    if REQUIRE_POSTGRES:
        raise RuntimeError("AGENTFORGE_TEST_DATABASE_URL is required for Stage 3.3-A2 acceptance")
    pytest.skip("set AGENTFORGE_TEST_DATABASE_URL", allow_module_level=True)

from agentforge.application.errors import GovernanceDecisionConflictError
from agentforge.domain.enums import (
    EventType,
    GovernanceDecision,
    GovernanceMode,
    ModelInvocationStatus,
    PrincipalType,
    ToolEffectType,
)
from agentforge.domain.governance import GovernancePolicyRule, PrincipalContext
from agentforge.domain.governance_decisions import (
    GovernanceIntentV1,
    PolicyEvaluation,
    evaluate_policy,
)
from agentforge.domain.models import ToolBinding
from agentforge.infrastructure.db.governance_decision_store import (
    PostgresGovernanceDecisionStore,
)
from agentforge.infrastructure.db.governance_store import PostgresGovernancePolicyStore
from agentforge.infrastructure.db.models import (
    AgentRow,
    AgentVersionRow,
    AgentVersionToolRow,
    DomainEventRow,
    GovernanceIntentRow,
    ModelInvocationRow,
    PolicyDecisionRow,
    ToolCallRow,
    ToolDefinitionRow,
    ToolExecutionAttemptRow,
    ToolProposalRow,
    ToolVersionRow,
)
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
async def test_a2_forward_migration_from_frozen_a1_head() -> None:
    config = _config()
    command.downgrade(config, "base")
    command.upgrade(config, "0017_governance_identity_policy")
    command.upgrade(config, "head")

    engine = create_engine(DATABASE_URL)
    async with engine.connect() as connection:
        tables = (
            (
                await connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public' "
                        "AND table_name IN ('governance_intents', 'policy_decisions') "
                        "ORDER BY table_name"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert list(tables) == ["governance_intents", "policy_decisions"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_a2_decision_is_exact_immutable_audited_and_creates_zero_physical_work() -> None:
    _reset_head()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    policy_store = PostgresGovernancePolicyStore(sessions)
    decision_store = PostgresGovernanceDecisionStore(sessions)

    agent_id = uuid4()
    agent_version_id = uuid4()
    tool_id = uuid4()
    tool_version_id = uuid4()

    rule = GovernancePolicyRule(
        rule_id="allow-read",
        priority=100,
        principal_roles_any=("operator",),
        agent_version_ids=(agent_version_id,),
        tool_version_ids=(tool_version_id,),
        effect_types=(ToolEffectType.READ,),
        principal_scopes=("tenant-a",),
        decision=GovernanceDecision.ALLOW,
    )
    draft = await policy_store.create_draft(
        policy_key="a2-exact",
        version_number=1,
        rules=(rule,),
    )
    policy = await policy_store.publish(draft.id)

    async with sessions() as session, session.begin():
        session.add_all(
            [
                AgentRow(id=agent_id, name=f"a2-agent-{agent_id}", description=""),
                ToolDefinitionRow(
                    id=tool_id,
                    name=f"a2-read-{tool_id}",
                    description="",
                ),
            ]
        )
        await session.flush()
        session.add(
            ToolVersionRow(
                id=tool_version_id,
                tool_id=tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.READ,
                implementation_ref="test://a2-read",
                approval_required=False,
                allow_no_approval_execution=False,
            )
        )
        session.add(
            AgentVersionRow(
                id=agent_version_id,
                agent_id=agent_id,
                version_number=1,
                instructions="A2 evaluator only",
                governance_mode=GovernanceMode.GOVERNED,
                policy_version_id=policy.id,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=agent_version_id,
                tool_version_id=tool_version_id,
                tool_alias="read",
            )
        )

    principal = PrincipalContext(
        principal_id=" user-1 ",
        principal_type=PrincipalType.USER,
        roles=("runtime:run:create", "operator"),
        principal_scope=" tenant-a ",
        authn_source=" oidc ",
    )
    runtime_store = PostgresRuntimeStore(sessions)
    run = await runtime_store.create_run(
        agent_version_id=agent_version_id,
        input_text="evaluate only",
        idempotency_key="a2-decision",
        principal_scope="ignored-body-scope",
        principal=principal,
    )

    invocation_id = uuid4()
    proposal_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            ModelInvocationRow(
                id=invocation_id,
                run_id=run.id,
                turn=1,
                status=ModelInvocationStatus.COMPLETED.value,
                outcome_type="TOOL_PROPOSAL",
                completed_at=datetime.now(UTC),
            )
        )
        await session.flush()
        session.add(
            ToolProposalRow(
                id=proposal_id,
                run_id=run.id,
                model_invocation_id=invocation_id,
                tool_name="read",
                arguments={"query": "hello", "nested": {"b": 2, "a": 1}},
            )
        )

    binding = ToolBinding(
        tool_version_id=tool_version_id,
        name="read",
        effect_type=ToolEffectType.READ,
    )
    intent = GovernanceIntentV1.create(
        run_id=run.id,
        agent_version_id=agent_version_id,
        proposal_id=proposal_id,
        binding=binding,
        arguments={"nested": {"a": 1, "b": 2}, "query": "hello"},
        principal=principal,
    )
    evaluation = evaluate_policy(
        policy,
        principal=principal,
        agent_version_id=agent_version_id,
        binding=binding,
    )
    assert evaluation.effective_decision is GovernanceDecision.ALLOW

    decision = await decision_store.record(
        intent=intent,
        policy_version_id=policy.id,
        evaluation=evaluation,
    )

    assert decision.run_id == run.id
    assert decision.proposal_id == proposal_id
    assert decision.tool_version_id == tool_version_id
    assert decision.policy_version_id == policy.id
    assert decision.requester_principal_id == "user-1"
    assert decision.principal_scope == "tenant-a"
    assert decision.effective_decision is GovernanceDecision.ALLOW
    assert decision.matched_rule_id == "allow-read"
    assert decision.intent_digest == intent.digest

    replay = await decision_store.record(
        intent=intent,
        policy_version_id=policy.id,
        evaluation=evaluation,
    )
    assert replay.id == decision.id

    with pytest.raises(GovernanceDecisionConflictError):
        await decision_store.record(
            intent=intent,
            policy_version_id=policy.id,
            evaluation=PolicyEvaluation(
                raw_decision=GovernanceDecision.DENY,
                effective_decision=GovernanceDecision.DENY,
                matched_rule_id=None,
            ),
        )

    async with sessions() as session:
        intent_row = (
            await session.execute(
                select(GovernanceIntentRow).where(GovernanceIntentRow.proposal_id == proposal_id)
            )
        ).scalar_one()
        decision_row = (
            await session.execute(
                select(PolicyDecisionRow).where(PolicyDecisionRow.proposal_id == proposal_id)
            )
        ).scalar_one()
        audit_events = (
            (
                await session.execute(
                    select(DomainEventRow).where(
                        DomainEventRow.run_id == run.id,
                        DomainEventRow.event_type == EventType.POLICY_DECIDED.value,
                    )
                )
            )
            .scalars()
            .all()
        )
        tool_calls = await session.scalar(select(func.count()).select_from(ToolCallRow))
        attempts = await session.scalar(select(func.count()).select_from(ToolExecutionAttemptRow))

        assert intent_row.digest == intent.digest
        assert intent_row.canonical_json == intent.canonical_json
        assert decision_row.intent_digest == intent.digest
        assert decision_row.governance_intent_id == intent_row.id
        assert len(audit_events) == 1
        assert audit_events[0].payload["intent_digest"] == intent.digest
        assert tool_calls == 0
        assert attempts == 0

    async with sessions() as session:
        with pytest.raises(DBAPIError):
            await session.execute(
                text(
                    "UPDATE policy_decisions SET matched_rule_id = 'tamper' WHERE id = :decision_id"
                ),
                {"decision_id": decision.id},
            )
            await session.commit()
        await session.rollback()

    async with sessions() as session:
        with pytest.raises(DBAPIError):
            await session.execute(
                text(
                    "UPDATE governance_intents SET canonical_json = '{}' "
                    "WHERE proposal_id = :proposal_id"
                ),
                {"proposal_id": proposal_id},
            )
            await session.commit()
        await session.rollback()

    await engine.dispose()


@pytest.mark.asyncio
async def test_a2_malformed_durable_policy_fails_closed_to_deny() -> None:
    _reset_head()
    engine = create_engine(DATABASE_URL)
    sessions = create_session_factory(engine)
    decision_store = PostgresGovernanceDecisionStore(sessions)

    policy_id = uuid4()
    agent_id = uuid4()
    agent_version_id = uuid4()
    tool_id = uuid4()
    tool_version_id = uuid4()

    async with sessions() as session, session.begin():
        await session.execute(
            text(
                "INSERT INTO governance_policy_versions "
                "(id, policy_key, version_number, status, rules, published_at) "
                "VALUES (:id, :policy_key, 1, 'PUBLISHED', CAST(:rules AS jsonb), "
                "CURRENT_TIMESTAMP)"
            ),
            {
                "id": policy_id,
                "policy_key": f"malformed-{policy_id}",
                "rules": json.dumps([{"not": "a valid governance rule"}]),
            },
        )
        session.add_all(
            [
                AgentRow(id=agent_id, name=f"malformed-agent-{agent_id}", description=""),
                ToolDefinitionRow(
                    id=tool_id,
                    name=f"malformed-read-{tool_id}",
                    description="",
                ),
            ]
        )
        await session.flush()
        session.add(
            ToolVersionRow(
                id=tool_version_id,
                tool_id=tool_id,
                version_number=1,
                input_schema={"type": "object"},
                effect_type=ToolEffectType.READ,
                implementation_ref="test://malformed-read",
                approval_required=False,
                allow_no_approval_execution=False,
            )
        )
        session.add(
            AgentVersionRow(
                id=agent_version_id,
                agent_id=agent_id,
                version_number=1,
                instructions="malformed policy must fail closed",
                governance_mode=GovernanceMode.GOVERNED,
                policy_version_id=policy_id,
            )
        )
        await session.flush()
        session.add(
            AgentVersionToolRow(
                agent_version_id=agent_version_id,
                tool_version_id=tool_version_id,
                tool_alias="read",
            )
        )

    principal = PrincipalContext(
        principal_id="user-malformed",
        principal_type=PrincipalType.USER,
        roles=("operator",),
        principal_scope="tenant-a",
        authn_source="test",
    )
    runtime_store = PostgresRuntimeStore(sessions)
    run = await runtime_store.create_run(
        agent_version_id=agent_version_id,
        input_text="malformed policy",
        idempotency_key="malformed-policy",
        principal_scope="ignored",
        principal=principal,
    )

    invocation_id = uuid4()
    proposal_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            ModelInvocationRow(
                id=invocation_id,
                run_id=run.id,
                turn=1,
                status=ModelInvocationStatus.COMPLETED.value,
                outcome_type="TOOL_PROPOSAL",
                completed_at=datetime.now(UTC),
            )
        )
        await session.flush()
        session.add(
            ToolProposalRow(
                id=proposal_id,
                run_id=run.id,
                model_invocation_id=invocation_id,
                tool_name="read",
                arguments={"query": "must deny"},
            )
        )

    binding = ToolBinding(
        tool_version_id=tool_version_id,
        name="read",
        effect_type=ToolEffectType.READ,
    )
    intent = GovernanceIntentV1.create(
        run_id=run.id,
        agent_version_id=agent_version_id,
        proposal_id=proposal_id,
        binding=binding,
        arguments={"query": "must deny"},
        principal=principal,
    )
    deny = PolicyEvaluation(
        raw_decision=GovernanceDecision.DENY,
        effective_decision=GovernanceDecision.DENY,
        matched_rule_id=None,
    )

    decision = await decision_store.record(
        intent=intent,
        policy_version_id=policy_id,
        evaluation=deny,
    )
    assert decision.effective_decision is GovernanceDecision.DENY
    assert decision.matched_rule_id is None

    async with sessions() as session:
        attempts = await session.scalar(select(func.count()).select_from(ToolExecutionAttemptRow))
        assert attempts == 0

    await engine.dispose()
