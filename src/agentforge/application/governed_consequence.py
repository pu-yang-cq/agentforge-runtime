from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from agentforge.domain.actions import ActionSnapshot, ExternalAction
from agentforge.domain.enums import (
    GovernanceDecision,
    GovernanceMode,
    ToolCallStatus,
    ToolEffectType,
)
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
    pending_call: ToolCall | None = None
    pending_snapshot: ActionSnapshot | None = None
    pending_action: ExternalAction | None = None

    def __post_init__(self) -> None:
        if self.evaluation.effective_decision is GovernanceDecision.ALLOW:
            if (
                self.prepared is None
                or self.denied_call is not None
                or self.pending_call is not None
                or self.pending_snapshot is not None
                or self.pending_action is not None
            ):
                raise ValueError("ALLOW plan requires exactly one prepared Stage 3.2 consequence")
            return

        if self.evaluation.effective_decision is GovernanceDecision.DENY:
            if (
                self.denied_call is None
                or self.prepared is not None
                or self.pending_call is not None
                or self.pending_snapshot is not None
                or self.pending_action is not None
            ):
                raise ValueError("DENY plan requires exactly one denied ToolCall")
            return

        if self.prepared is not None or self.denied_call is not None or self.pending_call is None:
            raise ValueError("REQUIRE_APPROVAL requires exactly one pending ToolCall")
        if self.evaluation.approval is None:
            raise ValueError("REQUIRE_APPROVAL consequence requires approval metadata")
        if self.binding.effect_type is ToolEffectType.READ:
            if self.pending_snapshot is not None or self.pending_action is not None:
                raise ValueError("READ approval cannot create ExternalAction intent")
            return
        if self.pending_snapshot is None or self.pending_action is None:
            raise ValueError("side-effect approval requires ActionSnapshot and ExternalAction")
        if self.pending_action.tool_call_id != self.pending_call.id:
            raise ValueError("pending ExternalAction must bind pending ToolCall")
        if self.pending_action.action_snapshot_id != self.pending_snapshot.id:
            raise ValueError("pending ExternalAction must bind pending ActionSnapshot")
        if self.pending_action.operation_id != self.pending_snapshot.operation_id:
            raise ValueError("pending action operation_id must match ActionSnapshot")


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

    pending_call = ToolCall.from_proposal(
        proposal,
        tool_version_id=binding.tool_version_id,
    )
    pending_call.await_approval()

    if binding.effect_type is ToolEffectType.READ:
        return GovernedToolPlan(
            intent=intent,
            evaluation=evaluation,
            binding=binding,
            pending_call=pending_call,
        )

    operation_id = uuid4()
    snapshot = ActionSnapshot.create(
        operation_id=operation_id,
        tool_version_id=binding.tool_version_id,
        effect_type=binding.effect_type,
        arguments=proposal.arguments,
        credential_ref=binding.credential_ref,
    )
    action = ExternalAction.awaiting_approval(
        run_id=proposal.run_id,
        tool_call_id=pending_call.id,
        action_snapshot_id=snapshot.id,
        operation_id=operation_id,
    )
    return GovernedToolPlan(
        intent=intent,
        evaluation=evaluation,
        binding=binding,
        pending_call=pending_call,
        pending_snapshot=snapshot,
        pending_action=action,
    )
