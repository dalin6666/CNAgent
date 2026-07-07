from __future__ import annotations

from typing import Any

from ..AgentTool import AgentTool
from .._runtime import ToolUseContext


async def spawnMultiAgent(tasks: list[dict[str, Any]], toolUseContext: ToolUseContext | None = None) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    context = toolUseContext or ToolUseContext()
    for task in tasks:
        result = await AgentTool.call(toolUseContext=context, **task)
        results.append(result)
    return results
