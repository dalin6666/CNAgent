from __future__ import annotations

from pathlib import Path
from typing import Any

from .._runtime import SimpleTool, ToolUseContext, expand_path


def _call(server: str, uri: str, toolUseContext: ToolUseContext | None = None, **_kwargs: Any) -> dict[str, Any]:
    state = toolUseContext.getAppState() if toolUseContext else None
    resources = state.mcp_resources.get(server, []) if state is not None else []
    for resource in resources:
        if resource.get('uri') == uri:
            return {'data': {'server': server, 'uri': uri, 'resource': resource}}
    if uri.startswith('file://'):
        path = expand_path(uri.removeprefix('file://'), toolUseContext.options.cwd if toolUseContext else None)
        return {'data': {'server': server, 'uri': uri, 'content': Path(path).read_text(encoding='utf-8', errors='replace')}}
    return {'data': {'server': server, 'uri': uri, 'resource': None}}


ReadMcpResourceTool = SimpleTool(
    name='ReadMcpResource',
    description_text='Read a specific MCP resource by server and URI.',
    prompt_text='Use after discovering the resource via ListMcpResourcesTool.',
    call_handler=_call,
    input_schema={'server': 'server name', 'uri': 'resource identifier'},
    output_schema={'resource': 'resource payload or file content'},
    user_facing_name='Read MCP Resource',
)
