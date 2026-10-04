from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ModelToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ModelMessage:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class ModelRequest:
    invocation_id: UUID
    run_id: UUID
    instructions: str
    messages: tuple[ModelMessage, ...]
    available_tools: tuple[ModelToolSpec, ...]


@dataclass(frozen=True, slots=True)
class ModelToolProposal:
    tool_name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ModelResponse:
    invocation_id: UUID
    text: str | None = None
    tool_proposal: ModelToolProposal | None = None

    def __post_init__(self) -> None:
        if (self.text is None) == (self.tool_proposal is None):
            raise ValueError("exactly one of text or tool_proposal must be set")
