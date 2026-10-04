from __future__ import annotations

from uuid import UUID

from agentforge.runtime.fake_model import FinalStep, ScriptedFakeModel, ToolStep
from agentforge.runtime.tools import FunctionTool, InMemoryToolRegistry

DEMO_TOOL_ID = UUID("2b05fe52-7338-48cc-9c62-d62d19c2b488")
DEMO_TOOL_VERSION_ID = UUID("efbf9388-4bc4-4309-949e-7ca4b935fc9a")
DEMO_AGENT_ID = UUID("894e3493-c4a9-4255-8b95-d54ba859f904")
DEMO_AGENT_VERSION_ID = UUID("57556857-4f0c-4450-a67c-9fcd28a5a5db")


def build_demo_registry() -> InMemoryToolRegistry:
    return InMemoryToolRegistry(
        [
            FunctionTool(
                version_id=DEMO_TOOL_VERSION_ID,
                name="echo_read",
                description="Return the supplied text without side effects.",
                input_schema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
                func=lambda text: {"echo": text},
            )
        ]
    )


def build_demo_model(input_text: str) -> ScriptedFakeModel:
    return ScriptedFakeModel(
        [
            ToolStep("echo_read", {"text": input_text}),
            FinalStep(f"Completed deterministic Wave-1 run for: {input_text}"),
        ]
    )
