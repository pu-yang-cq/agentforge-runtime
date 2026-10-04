from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast
from uuid import uuid4

from agentforge.application.ports import (
    SideEffectInvocation,
    SideEffectTool,
    Tool,
    ToolRegistry,
)
from agentforge.domain.actions import ActionSnapshot, ExternalAction
from agentforge.domain.enums import ExternalActionStatus, ToolCallStatus, ToolEffectType
from agentforge.domain.models import (
    AgentVersion,
    ToolBinding,
    ToolCall,
    ToolExecutionAttempt,
    ToolProposal,
)


@dataclass(slots=True)
class PreparedToolCall:
    call: ToolCall
    tool: Tool
    binding: ToolBinding


@dataclass(slots=True)
class PreparedExternalAction:
    call: ToolCall
    snapshot: ActionSnapshot
    action: ExternalAction
    tool: SideEffectTool
    binding: ToolBinding


class ToolCoordinator:
    """Separate durable acceptance, Action Commit, and physical Tool invocation."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    @staticmethod
    def _binding(name: str, agent_version: AgentVersion) -> ToolBinding:
        matches = [binding for binding in agent_version.tool_bindings if binding.name == name]
        if len(matches) != 1:
            raise PermissionError(f"tool is not uniquely bound to agent version: {name}")
        return matches[0]

    def _resolve_bound_tool(self, binding: ToolBinding, agent_version: AgentVersion) -> Tool:
        tool = self._registry.resolve(binding.name, agent_version.tool_bindings)
        if tool.version_id != binding.tool_version_id:
            raise ValueError("resolved tool version no longer matches immutable binding")
        return tool

    def _resolve_side_effect_tool(
        self,
        binding: ToolBinding,
        agent_version: AgentVersion,
    ) -> SideEffectTool:
        tool = self._resolve_bound_tool(binding, agent_version)
        if not isinstance(tool, SideEffectTool):
            raise PermissionError(
                f"tool adapter does not implement the side-effect contract: {binding.name}"
            )
        return cast(SideEffectTool, tool)

    def prepare_model_tool(
        self,
        *,
        proposal: ToolProposal,
        agent_version: AgentVersion,
    ) -> PreparedToolCall | PreparedExternalAction:
        binding = self._binding(proposal.tool_name, agent_version)
        if binding.effect_type is ToolEffectType.READ:
            return self._prepare_read_with_binding(
                proposal=proposal,
                agent_version=agent_version,
                binding=binding,
            )
        return self._prepare_side_effect_with_binding(
            proposal=proposal,
            agent_version=agent_version,
            binding=binding,
        )

    def prepare_read(
        self, *, proposal: ToolProposal, agent_version: AgentVersion
    ) -> PreparedToolCall:
        binding = self._binding(proposal.tool_name, agent_version)
        return self._prepare_read_with_binding(
            proposal=proposal,
            agent_version=agent_version,
            binding=binding,
        )

    def _prepare_read_with_binding(
        self,
        *,
        proposal: ToolProposal,
        agent_version: AgentVersion,
        binding: ToolBinding,
    ) -> PreparedToolCall:
        if binding.effect_type is not ToolEffectType.READ:
            raise PermissionError(f"tool is not a READ ToolVersion: {proposal.tool_name}")
        tool = self._resolve_bound_tool(binding, agent_version)
        call = ToolCall.from_proposal(proposal, tool_version_id=tool.version_id)
        call.ready()
        call.start()
        return PreparedToolCall(call=call, tool=tool, binding=binding)

    def prepare_side_effect(
        self, *, proposal: ToolProposal, agent_version: AgentVersion
    ) -> PreparedExternalAction:
        binding = self._binding(proposal.tool_name, agent_version)
        return self._prepare_side_effect_with_binding(
            proposal=proposal,
            agent_version=agent_version,
            binding=binding,
        )

    def _prepare_side_effect_with_binding(
        self,
        *,
        proposal: ToolProposal,
        agent_version: AgentVersion,
        binding: ToolBinding,
    ) -> PreparedExternalAction:
        if not binding.stage32_side_effect_executable:
            raise PermissionError(
                f"ToolVersion is not Stage-3.2 side-effect executable: {proposal.tool_name}"
            )
        tool = self._resolve_side_effect_tool(binding, agent_version)
        call = ToolCall.from_proposal(proposal, tool_version_id=binding.tool_version_id)
        call.ready()
        operation_id = uuid4()
        snapshot = ActionSnapshot.create(
            operation_id=operation_id,
            tool_version_id=binding.tool_version_id,
            effect_type=binding.effect_type,
            arguments=proposal.arguments,
            credential_ref=binding.credential_ref,
        )
        action = ExternalAction.create(
            run_id=proposal.run_id,
            tool_call_id=call.id,
            action_snapshot_id=snapshot.id,
            operation_id=operation_id,
        )
        return PreparedExternalAction(
            call=call,
            snapshot=snapshot,
            action=action,
            tool=tool,
            binding=binding,
        )

    def prepare_recovered_read(
        self, *, call: ToolCall, agent_version: AgentVersion
    ) -> PreparedToolCall:
        if call.status is not ToolCallStatus.READY:
            raise ValueError("recovered READ call must be READY")
        if call.tool_version_id is None:
            raise ValueError("recovered READ call must bind a tool version")
        binding = self._binding(call.tool_name, agent_version)
        if binding.effect_type is not ToolEffectType.READ:
            raise ValueError("recovered ToolCall is not a READ ToolVersion")
        tool = self._resolve_bound_tool(binding, agent_version)
        if tool.version_id != call.tool_version_id:
            raise ValueError("recovered READ call tool version no longer matches binding")
        call.start()
        return PreparedToolCall(call=call, tool=tool, binding=binding)

    def prepare_recovered_side_effect(
        self,
        *,
        call: ToolCall,
        snapshot: ActionSnapshot,
        action: ExternalAction,
        agent_version: AgentVersion,
    ) -> PreparedExternalAction:
        if call.status is not ToolCallStatus.READY:
            raise ValueError("recovered side-effect ToolCall must be READY")
        if action.status is not ExternalActionStatus.READY or action.current_attempt_id is not None:
            raise ValueError("recovered ExternalAction must be READY without an active attempt")
        if call.id != action.tool_call_id or snapshot.id != action.action_snapshot_id:
            raise ValueError("recovered side-effect durable identity mismatch")
        if call.tool_version_id != snapshot.tool_version_id:
            raise ValueError("recovered side-effect ToolVersion mismatch")
        if call.arguments != snapshot.arguments or action.operation_id != snapshot.operation_id:
            raise ValueError("recovered side-effect snapshot mismatch")
        binding = self._binding(call.tool_name, agent_version)
        if binding.tool_version_id != snapshot.tool_version_id:
            raise ValueError("recovered side-effect binding no longer matches snapshot")
        if not binding.stage32_side_effect_executable:
            raise PermissionError("recovered ToolVersion is not Stage-3.2 executable")
        tool = self._resolve_side_effect_tool(binding, agent_version)
        return PreparedExternalAction(
            call=call,
            snapshot=snapshot,
            action=action,
            tool=tool,
            binding=binding,
        )

    async def execute_prepared(self, prepared: PreparedToolCall) -> ToolCall:
        call = prepared.call
        try:
            raw_result = await prepared.tool.invoke(call.arguments)
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

    async def execute_side_effect(
        self,
        prepared: PreparedExternalAction,
        attempt: ToolExecutionAttempt,
    ) -> ToolCall:
        if prepared.call.status is not ToolCallStatus.EXECUTING:
            raise RuntimeError("side-effect adapter call requires EXECUTING ToolCall")
        if prepared.action.status is not ExternalActionStatus.EXECUTING:
            raise RuntimeError("side-effect adapter call requires EXECUTING ExternalAction")
        if prepared.action.current_attempt_id != attempt.id:
            raise RuntimeError("side-effect attempt is not the current authorized attempt")
        if attempt.external_action_id != prepared.action.id:
            raise RuntimeError("side-effect attempt does not reference ExternalAction")
        invocation = SideEffectInvocation(
            operation_id=prepared.action.operation_id,
            arguments=dict(prepared.snapshot.arguments),
            credential_ref=prepared.snapshot.credential_ref,
            idempotency_key=(
                str(prepared.action.operation_id)
                if prepared.binding.idempotency_supported
                else None
            ),
        )
        raw_result = await prepared.tool.invoke_side_effect(invocation)
        encoded = json.dumps(
            raw_result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        prepared.call.succeed(json.loads(encoded))
        return prepared.call


def tool_result_message_content(result: object) -> str:
    """Canonical JSON representation fed back to the model."""
    return json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
