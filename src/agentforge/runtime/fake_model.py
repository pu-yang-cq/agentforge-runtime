from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from agentforge.application.ports import ModelGateway
from agentforge.domain.model_contract import ModelRequest, ModelResponse, ModelToolProposal


@dataclass(frozen=True, slots=True)
class ToolStep:
    tool_name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class FinalStep:
    text: str


class ScriptedFakeModel(ModelGateway):
    def __init__(self, steps: list[ToolStep | FinalStep]) -> None:
        self._steps = deque(steps)
        self.requests: list[ModelRequest] = []

    async def invoke(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if not self._steps:
            raise RuntimeError("fake model script exhausted")
        step = self._steps.popleft()
        if isinstance(step, ToolStep):
            return ModelResponse(
                invocation_id=request.invocation_id,
                tool_proposal=ModelToolProposal(step.tool_name, step.arguments),
            )
        return ModelResponse(invocation_id=request.invocation_id, text=step.text)
