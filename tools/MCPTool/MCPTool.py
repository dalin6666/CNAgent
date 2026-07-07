from __future__ import annotations

from typing import Any

from .._runtime import SimpleTool, ToolUseContext


def _call(server: str, tool: str, arguments: dict[str, Any] | None = None, toolUseContext: ToolUseContext | None = None, **_kwargs: Any) -> dict[str, Any]:
    state = toolUseContext.getAppState() if toolUseContext else None
    handlers = state.mcp_handlers if state is not None else {}
    handler = handlers.get(f'{server}::{tool}') if handlers else None
    if callable(handler):
        result = handler(arguments or {})
        return {'data': {'server': server, 'tool': tool, 'result': result, 'handled': True}}
    return {'data': {'server': server, 'tool': tool, 'arguments': arguments or {}, 'handled': False, 'message': 'No Python handler registered for this MCP tool.'}}


MCPTool = SimpleTool(
    name='MCP',
    description_text='Invoke a registered MCP handler in the Python port runtime.',
    prompt_text='Use when an MCP server/tool pair has been registered into the shared app state.',
    call_handler=_call,
    input_schema={'server': 'server name', 'tool': 'tool name', 'arguments': 'tool payload'},
    output_schema={'handled': 'whether a Python handler was found'},
    user_facing_name='MCP',
)
