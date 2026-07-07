from __future__ import annotations

from typing import Any

from .._runtime import SimpleTool, ToolUseContext


def _call(server: str, token: str | None = None, clear: bool = False, toolUseContext: ToolUseContext | None = None, **_kwargs: Any) -> dict[str, Any]:
    state = toolUseContext.getAppState() if toolUseContext else None
    store = state.mcp_auth if state is not None else {}
    if clear:
        store.pop(server, None)
        return {'data': {'server': server, 'authenticated': False, 'cleared': True}}
    if token is not None:
        store[server] = token
        return {'data': {'server': server, 'authenticated': True, 'stored': True}}
    return {'data': {'server': server, 'authenticated': server in store, 'token': store.get(server)}}


McpAuthTool = SimpleTool(
    name='McpAuth',
    description_text='Read, set, or clear MCP authentication tokens in shared state.',
    prompt_text='Provide a server plus a token to store it, or set `clear=true` to remove it.',
    call_handler=_call,
    input_schema={'server': 'server name', 'token': 'optional token', 'clear': 'remove stored auth'},
    output_schema={'authenticated': 'whether credentials are currently present'},
    user_facing_name='MCP Auth',
)
