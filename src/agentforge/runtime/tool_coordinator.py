from __future__ import annotations

import json
from dataclasses import dataclass

from agentforge.application.ports import Tool, ToolRegistry
from agentforge.domain.enums import ToolCallStatus
from agentforge.domain.models import AgentVersion, ToolBinding, ToolCall, ToolProposal


@dataclass(slots=True)
class PreparedToolCall:
    call: ToolCall
    tool: Tool
    binding: ToolBinding


class ToolCoordinator:
    """Wave-1 coordinator for READ-only tools.

    It separates acceptance from execution so the ToolCall can be durably
    persisted in EXECUTING state before the external/read boundary is crossed.
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    @staticmethod
    def _binding(name: str, agent_version: AgentVersion) -> ToolBinding:
        matches = [binding for binding in agent_version.tool_bindings if binding.name == name]
        if len(matches) != 1:
            raise PermissionError(f"tool is not uniquely bound to agent version: {name}")
        return matches[0]

    def prepare_read(
        self, *, proposal: ToolProposal, agent_version: AgentVersion
    ) -> PreparedToolCall:
        binding = self._binding(proposal.tool_name, agent_version)
        tool = self._registry.resolve(proposal.tool_name, agent_version.tool_bindings)
        call = ToolCall.from_proposal(proposal, tool_version_id=tool.version_id)
        call.ready()
        call.start()
        return PreparedToolCall(call=call, tool=tool, binding=binding)

    def prepare_recovered_read(
        self, *, call: ToolCall, agent_version: AgentVersion
    ) -> PreparedToolCall:
        if call.status is not ToolCallStatus.READY:
            raise ValueError("recovered READ call must be READY")
        if call.tool_version_id is None:
            raise ValueError("recovered READ call must bind a tool version")
        binding = self._binding(call.tool_name, agent_version)
        tool = self._registry.resolve(call.tool_name, agent_version.tool_bindings)
        if (
            tool.version_id != call.tool_version_id
            or binding.tool_version_id != call.tool_version_id
        ):
            raise ValueError("recovered READ call tool version no longer matches binding")
        call.start()
        return PreparedToolCall(call=call, tool=tool, binding=binding)

    async def execute_prepared(self, prepared: PreparedToolCall) -> ToolCall:
        call = prepared.call
        try:
            raw_result = await prepared.tool.invoke(call.arguments)
            # Tool results are durable JSON facts. Normalize before declaring
            # success so persistence cannot fail later on a Python-only object.
            encoded = json.dumps(
                raw_result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            result = json.loads(encoded)
        except Exception as exc:
            call.fail(str(exc))
            raise
        call.succeed(result)
        return call


def tool_result_message_content(result: object) -> str:
    """Canonical JSON representation fed back to the model."""
    return json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
