from __future__ import annotations

"""Auto-generated Python mirror of `D:/code_project/claude-code-main/tools/ListMcpResourcesTool/prompt.ts`."""

from typing import Any
from .._mirror import placeholder_class, placeholder_function

SOURCE_PATH = r"D:/code_project/claude-code-main/tools/ListMcpResourcesTool/prompt.ts"
__all__ = ['DESCRIPTION', 'LIST_MCP_RESOURCES_TOOL_NAME', 'PROMPT']

DESCRIPTION = "\nLists available resources from configured MCP servers.\nEach resource object includes a 'server' field indicating which server it's from.\n\nUsage examples:\n- List all resources from all servers: \\"
LIST_MCP_RESOURCES_TOOL_NAME = 'ListMcpResourcesTool'
PROMPT = "\nList available resources from configured MCP servers.\nEach returned resource will include all standard MCP resource fields plus a 'server' field \nindicating which server the resource belongs to.\n\nParameters:\n- server (optional): The name of a specific MCP server to get resources from. If not provided,\n  resources from all servers will be returned.\n"
