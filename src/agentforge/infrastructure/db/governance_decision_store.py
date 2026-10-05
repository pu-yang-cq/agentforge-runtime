from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentforge.application.errors import GovernanceDecisionConflictError
from agentforge.application.ports import GovernanceDecisionStore
from agentforge.domain.enums import EventType, GovernanceDecision
from agentforge.domain.governance import (
    GovernancePolicyRule,
    GovernancePolicyVersion,
    PrincipalContext,
)
from agentforge.domain.governance_decisions import (
    GovernanceIntentV1,
    PolicyDecision,
    PolicyEvaluation,
    evaluate_policy,
)
from agentforge.domain.models import ToolBinding
from agentforge.infrastructure.db.models import (
    AgentVersionToolRow,
    DomainEventRow,
    GovernanceIntentRow,
    GovernancePolicyVersionRow,
    PolicyDecisionRow,
    RunCounterRow,
    RunRow,
    ToolProposalRow,
    ToolVersionRow,
)


def _decision_from_row(row: PolicyDecisionRow) -> PolicyDecision:
    return PolicyDecision(
        id=row.id,
        run_id=row.run_id,
        proposal_id=row.proposal_id,
        tool_version_id=row.tool_version_id,
        policy_version_id=row.policy_version_id,
        requester_principal_id=row.requester_principal_id,
        principal_scope=row.principal_scope,
        effective_decision=row.effective_decision,
        matched_rule_id=row.matched_rule_id,
        intent_digest=row.intent_digest,
        created_at=row.created_at,
    )


def _fail_closed_evaluation() -> PolicyEvaluation:
    return PolicyEvaluation(
        raw_decision=GovernanceDecision.DENY,
        effective_decision=GovernanceDecision.DENY,
        matched_rule_id=None,
    )


class PostgresGovernanceDecisionStore(GovernanceDecisionStore):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def get_by_proposal(self, proposal_id: UUID) -> PolicyDecision | None:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(PolicyDecisionRow).where(
                        PolicyDecisionRow.proposal_id == proposal_id
                    )
                )
            ).scalar_one_or_none()
            return None if row is None else _decision_from_row(row)

    async def record(
        self,
        *,
        intent: GovernanceIntentV1,
        policy_version_id: UUID,
        evaluation: PolicyEvaluation,
    ) -> PolicyDecision:
        async with self._sessions() as session, session.begin():
            existing = (
                await session.execute(
                    select(PolicyDecisionRow).where(
                        PolicyDecisionRow.proposal_id == intent.proposal_id
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing_intent = await session.get(
                    GovernanceIntentRow,
                    existing.governance_intent_id,
                )
                if existing_intent is None:
                    raise RuntimeError("PolicyDecision points to a missing GovernanceIntent")
                same = (
                    existing.run_id == intent.run_id
                    and existing.tool_version_id == intent.tool_version_id
                    and existing.policy_version_id == policy_version_id
                    and existing.requester_principal_id == intent.requester_principal_id
                    and existing.principal_scope == intent.principal_scope
                    and existing.effective_decision is evaluation.effective_decision
                    and existing.matched_rule_id == evaluation.matched_rule_id
                    and existing.intent_digest == intent.digest
                    and existing_intent.canonical_json == intent.canonical_json
                    and existing_intent.digest == intent.digest
                )
                if same:
                    return _decision_from_row(existing)
                raise GovernanceDecisionConflictError(
                    "proposal already has a different immutable governance decision"
                )

            run = (
                await session.execute(
                    select(RunRow).where(RunRow.id == intent.run_id).with_for_update()
                )
            ).scalar_one_or_none()
            if run is None:
                raise KeyError(f"run not found: {intent.run_id}")
            if run.policy_version_id != policy_version_id:
                raise ValueError("PolicyDecision policy_version_id does not match pinned Run policy")
            if run.agent_version_id != intent.agent_version_id:
                raise ValueError("GovernanceIntent AgentVersion does not match durable Run")
            if (
                run.requester_principal_id != intent.requester_principal_id
                or run.requester_principal_type is not intent.requester_principal_type
                or tuple(run.requester_roles or ()) != intent.requester_roles
                or run.requester_scope != intent.principal_scope
            ):
                raise ValueError("GovernanceIntent requester does not match durable Run snapshot")
            if run.requester_authn_source is None:
                raise ValueError("GOVERNED Run is missing durable authn_source")

            proposal = await session.get(ToolProposalRow, intent.proposal_id)
            if proposal is None:
                raise KeyError(f"tool proposal not found: {intent.proposal_id}")
            if proposal.run_id != intent.run_id:
                raise ValueError("GovernanceIntent proposal does not belong to durable Run")

            binding_row = (
                await session.execute(
                    select(AgentVersionToolRow).where(
                        AgentVersionToolRow.agent_version_id == intent.agent_version_id,
                        AgentVersionToolRow.tool_version_id == intent.tool_version_id,
                    )
                )
            ).scalar_one_or_none()
            if binding_row is None or binding_row.tool_alias != proposal.tool_name:
                raise ValueError("GovernanceIntent ToolVersion is not the immutable proposal binding")

            tool_version = await session.get(ToolVersionRow, intent.tool_version_id)
            if tool_version is None:
                raise KeyError(f"tool version not found: {intent.tool_version_id}")
            binding = ToolBinding(
                tool_version_id=tool_version.id,
                name=binding_row.tool_alias,
                effect_type=tool_version.effect_type,
                approval_required=tool_version.approval_required,
                allow_no_approval_execution=tool_version.allow_no_approval_execution,
            )
            principal = PrincipalContext(
                principal_id=run.requester_principal_id,
                principal_type=run.requester_principal_type,
                roles=tuple(run.requester_roles or ()),
                principal_scope=run.requester_scope,
                authn_source=run.requester_authn_source,
            )
            durable_intent = GovernanceIntentV1.create(
                run_id=run.id,
                agent_version_id=run.agent_version_id,
                proposal_id=proposal.id,
                binding=binding,
                arguments=proposal.arguments,
                principal=principal,
            )
            if (
                durable_intent.canonical_json != intent.canonical_json
                or durable_intent.digest != intent.digest
            ):
                raise ValueError("GovernanceIntent does not match durable proposal identity")

            policy_row = await session.get(GovernancePolicyVersionRow, policy_version_id)
            if policy_row is None:
                raise KeyError(f"governance policy not found: {policy_version_id}")
            try:
                policy = GovernancePolicyVersion(
                    id=policy_row.id,
                    policy_key=policy_row.policy_key,
                    version_number=policy_row.version_number,
                    status=policy_row.status,
                    rules=tuple(
                        GovernancePolicyRule.from_record(record) for record in policy_row.rules
                    ),
                    created_at=policy_row.created_at,
                    published_at=policy_row.published_at,
                    retired_at=policy_row.retired_at,
                )
                durable_evaluation = evaluate_policy(
                    policy,
                    principal=principal,
                    agent_version_id=run.agent_version_id,
                    binding=binding,
                )
            except (AttributeError, TypeError, ValueError):
                durable_evaluation = _fail_closed_evaluation()

            if durable_evaluation != evaluation:
                raise ValueError("PolicyEvaluation does not match durable pinned policy")

            intent_row = GovernanceIntentRow(
                id=uuid4(),
                format_version=intent.format_version,
                run_id=intent.run_id,
                agent_version_id=intent.agent_version_id,
                proposal_id=intent.proposal_id,
                tool_version_id=intent.tool_version_id,
                effect_type=intent.effect_type,
                requester_principal_id=intent.requester_principal_id,
                requester_principal_type=intent.requester_principal_type,
                requester_roles=list(intent.requester_roles),
                principal_scope=intent.principal_scope,
                canonical_json=intent.canonical_json,
                digest=intent.digest,
            )
            decision_row = PolicyDecisionRow(
                id=uuid4(),
                governance_intent_id=intent_row.id,
                run_id=intent.run_id,
                proposal_id=intent.proposal_id,
                tool_version_id=intent.tool_version_id,
                policy_version_id=policy_version_id,
                requester_principal_id=intent.requester_principal_id,
                principal_scope=intent.principal_scope,
                effective_decision=evaluation.effective_decision,
                matched_rule_id=evaluation.matched_rule_id,
                intent_digest=intent.digest,
            )
            session.add_all([intent_row, decision_row])

            sequence_result = await session.execute(
                update(RunCounterRow)
                .where(RunCounterRow.run_id == run.id)
                .values(event_sequence=RunCounterRow.event_sequence + 1)
                .returning(RunCounterRow.event_sequence)
            )
            sequence = sequence_result.scalar_one()
            session.add(
                DomainEventRow(
                    id=uuid4(),
                    run_id=run.id,
                    sequence=sequence,
                    event_type=EventType.POLICY_DECIDED.value,
                    payload={
                        "policy_decision_id": str(decision_row.id),
                        "proposal_id": str(intent.proposal_id),
                        "tool_version_id": str(intent.tool_version_id),
                        "policy_version_id": str(policy_version_id),
                        "effective_decision": evaluation.effective_decision.value,
                        "matched_rule_id": evaluation.matched_rule_id,
                        "intent_digest": intent.digest,
                    },
                )
            )

            await session.flush()
            await session.refresh(decision_row)
            return _decision_from_row(decision_row)
