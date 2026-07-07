from __future__ import annotations

from ..schemas import ToolResult
from .base import BaseTool, ToolRuntimeContext


class EchoTool(BaseTool):
    name = "echo"
    description = "Echo text back to the agent."
    permission_group = "lookup"
    aliases = ("print", "say")
    strict = True
    max_result_size_chars = 4_000
    output_schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
    }
    input_schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    async def run(
        self,
        arguments: dict[str, str],
        context: ToolRuntimeContext,
    ) -> ToolResult:
        del context
        text = arguments.get("text", "")
        output_text = self.truncate_text(str(text), limit=100_000)
        return self.build_result(
            arguments,
            output={"text": output_text},
            summary=f"Echoed {len(output_text)} chars.",
        )
