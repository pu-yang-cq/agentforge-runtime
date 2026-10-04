from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from agentforge.application.ports import ModelGateway, ToolRegistry
from agentforge.domain.model_contract import ModelMessage, ModelRequest
from agentforge.domain.models import AgentVersion, ToolProposal


@dataclass(frozen=True, slots=True)
class FinalDecision:
    model_invocation_id: UUID
    text: str


@dataclass(frozen=True, slots=True)
class ToolDecision:
    proposal: ToolProposal


RunnerDecision = FinalDecision | ToolDecision


class NativeRunner:
    """Provider-neutral reasoning component; never executes tools or mutates persistence."""

    def __init__(self, model_gateway: ModelGateway, tool_registry: ToolRegistry) -> None:
        self._models = model_gateway
        self._tools = tool_registry

    def prepare_request(
        self,
        *,
        invocation_id: UUID,
        run_id: UUID,
        agent_version: AgentVersion,
        messages: tuple[ModelMessage, ...],
    ) -> ModelRequest:
        """Build and validate the local request before a durable model-call permit.

        Resolving visible/bound Tool specs is local configuration work. If it
        fails, no ModelInvocation should be recorded because no provider request
        is allowed to cross the external boundary.
        """
        return ModelRequest(
            invocation_id=invocation_id,
            run_id=run_id,
            instructions=agent_version.instructions,
            messages=messages,
            available_tools=self._tools.specs(agent_version.tool_bindings),
        )

    async def decide_prepared(self, request: ModelRequest) -> RunnerDecision:
        response = await self._models.invoke(request)
        if response.invocation_id != request.invocation_id:
            raise RuntimeError("model adapter returned a mismatched invocation id")
        if response.text is not None:
            return FinalDecision(response.invocation_id, response.text)
        proposal = response.tool_proposal
        if proposal is None:
            raise RuntimeError("model adapter returned neither final text nor a tool proposal")
        return ToolDecision(
            ToolProposal.create(
                run_id=request.run_id,
                model_invocation_id=response.invocation_id,
                tool_name=proposal.tool_name,
                arguments=proposal.arguments,
            )
        )

    async def decide(
        self,
        *,
        invocation_id: UUID,
        run_id: UUID,
        agent_version: AgentVersion,
        messages: tuple[ModelMessage, ...],
    ) -> RunnerDecision:
        """Convenience method for pure Runner tests; durable Runtime uses the split API."""
        request = self.prepare_request(
            invocation_id=invocation_id,
            run_id=run_id,
            agent_version=agent_version,
            messages=messages,
        )
        return await self.decide_prepared(request)
