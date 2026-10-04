from __future__ import annotations

import json
from dataclasses import dataclass

from agentforge.application.ports import Tool, ToolRegistry
from agentforge.domain.enums import ToolCallStatus
from agentforge.domain.models import AgentVersion, ToolCall, ToolProposal


@dataclass(slots=True)
class PreparedToolCall:
    call: ToolCall
    tool: Tool


class ToolCoordinator:
    """Wave-1 coordinator for READ-only tools.

    It separates acceptance from execution so the ToolCall can be durably
    persisted in EXECUTING state before the external/read boundary is crossed.
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def prepare_read(
        self, *, proposal: ToolProposal, agent_version: AgentVersion
    ) -> PreparedToolCall:
        tool = self._registry.resolve(proposal.tool_name, agent_version.tool_bindings)
        call = ToolCall.from_proposal(proposal, tool_version_id=tool.version_id)
        call.ready()
        call.start()
        return PreparedToolCall(call=call, tool=tool)

    def prepare_recovered_read(
        self, *, call: ToolCall, agent_version: AgentVersion
    ) -> PreparedToolCall:
        if call.status is not ToolCallStatus.READY:
            raise ValueError("recovered READ call must be READY")
        if call.tool_version_id is None:
            raise ValueError("recovered READ call must bind a tool version")
        tool = self._registry.resolve(call.tool_name, agent_version.tool_bindings)
        if tool.version_id != call.tool_version_id:
            raise ValueError("recovered READ call tool version no longer matches binding")
        call.start()
        return PreparedToolCall(call=call, tool=tool)

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
