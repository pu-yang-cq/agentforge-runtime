from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from agentforge.domain.enums import GovernanceDecision, GovernanceMode, ToolCallStatus
from agentforge.domain.governance import GovernancePolicyVersion, PrincipalContext
from agentforge.domain.governance_decisions import (
    GovernanceIntentV1,
    PolicyEvaluation,
    evaluate_policy,
)
from agentforge.domain.models import AgentVersion, Run, ToolBinding, ToolCall, ToolProposal
from agentforge.runtime.tool_coordinator import (
    PreparedExternalAction,
    PreparedToolCall,
    ToolCoordinator,
)


@dataclass(frozen=True, slots=True)
class GovernedToolPlan:
    intent: GovernanceIntentV1
    evaluation: PolicyEvaluation
    binding: ToolBinding
    prepared: PreparedToolCall | PreparedExternalAction | None = None
    denied_call: ToolCall | None = None

    def __post_init__(self) -> None:
        if self.evaluation.effective_decision is GovernanceDecision.ALLOW:
            if self.prepared is None or self.denied_call is not None:
                raise ValueError("ALLOW plan requires exactly one prepared Stage 3.2 consequence")
        elif self.evaluation.effective_decision is GovernanceDecision.DENY:
            if self.denied_call is None or self.prepared is not None:
                raise ValueError("DENY plan requires exactly one denied ToolCall")
        elif self.prepared is not None or self.denied_call is not None:
            raise ValueError("REQUIRE_APPROVAL cannot create B execution consequence")


def _principal_from_run(run: Run) -> PrincipalContext:
    if (
        run.requester_principal_id is None
        or run.requester_principal_type is None
        or run.requester_roles is None
        or run.requester_scope is None
        or run.requester_authn_source is None
    ):
        raise ValueError("GOVERNED Run is missing durable requester snapshot")
    return PrincipalContext(
        principal_id=run.requester_principal_id,
        principal_type=run.requester_principal_type,
        roles=run.requester_roles,
        principal_scope=run.requester_scope,
        authn_source=run.requester_authn_source,
    )


def _binding_for_proposal(proposal: ToolProposal, agent_version: AgentVersion) -> ToolBinding:
    matches = tuple(
        binding for binding in agent_version.tool_bindings if binding.name == proposal.tool_name
    )
    if len(matches) != 1:
        raise PermissionError(f"tool is not uniquely bound to agent version: {proposal.tool_name}")
    return matches[0]


def plan_governed_tool_consequence(
    *,
    run: Run,
    agent_version: AgentVersion,
    proposal: ToolProposal,
    policy: GovernancePolicyVersion,
    tools: ToolCoordinator,
) -> GovernedToolPlan:
    if agent_version.governance_mode is not GovernanceMode.GOVERNED:
        raise ValueError("governed consequence planner requires GOVERNED AgentVersion")
    if run.agent_version_id != agent_version.id:
        raise ValueError("Run AgentVersion does not match governed execution specification")
    if (
        run.policy_version_id is None
        or agent_version.policy_version_id is None
        or run.policy_version_id != agent_version.policy_version_id
        or policy.id != run.policy_version_id
    ):
        raise ValueError("governed consequence requires exact pinned policy identity")
    if proposal.run_id != run.id:
        raise ValueError("ToolProposal does not belong to governed Run")

    principal = _principal_from_run(run)
    binding = _binding_for_proposal(proposal, agent_version)
    intent = GovernanceIntentV1.create(
        run_id=run.id,
        agent_version_id=agent_version.id,
        proposal_id=proposal.id,
        binding=binding,
        arguments=proposal.arguments,
        principal=principal,
    )
    evaluation = evaluate_policy(
        policy,
        principal=principal,
        agent_version_id=agent_version.id,
        binding=binding,
    )

    if evaluation.effective_decision is GovernanceDecision.ALLOW:
        prepared = tools.prepare_model_tool(
            proposal=proposal,
            agent_version=agent_version,
        )
        return GovernedToolPlan(
            intent=intent,
            evaluation=evaluation,
            binding=binding,
            prepared=prepared,
        )

    if evaluation.effective_decision is GovernanceDecision.DENY:
        denied_call = ToolCall(
            id=uuid4(),
            run_id=proposal.run_id,
            proposal_id=proposal.id,
            tool_version_id=binding.tool_version_id,
            tool_name=proposal.tool_name,
            arguments=proposal.arguments,
            status=ToolCallStatus.DENIED,
            error="GOVERNANCE_DENIED",
        )
        return GovernedToolPlan(
            intent=intent,
            evaluation=evaluation,
            binding=binding,
            denied_call=denied_call,
        )

    return GovernedToolPlan(
        intent=intent,
        evaluation=evaluation,
        binding=binding,
    )
