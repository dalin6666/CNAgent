from __future__ import annotations

from typing import Any

from .._runtime import SimpleTool, ToolUseContext


def _call(server: str | None = None, cursor: str | None = None, toolUseContext: ToolUseContext | None = None, **_kwargs: Any) -> dict[str, Any]:
    del cursor
    state = toolUseContext.getAppState() if toolUseContext else None
    resources = state.mcp_resources if state is not None else {}
    if server is not None:
        payload = list(resources.get(server, []))
    else:
        payload = [{'server': server_name, **resource} for server_name, server_resources in resources.items() for resource in server_resources]
    return {'data': {'resources': payload, 'count': len(payload)}}


ListMcpResourcesTool = SimpleTool(
    name='ListMcpResources',
    description_text='List registered MCP resources from the shared Python port state.',
    prompt_text='Provide `server` to filter to a single MCP server.',
    call_handler=_call,
    input_schema={'server': 'optional server name'},
    output_schema={'resources': 'available resources'},
    user_facing_name='List MCP Resources',
)
