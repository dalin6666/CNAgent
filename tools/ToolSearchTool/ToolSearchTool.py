from __future__ import annotations

from .._runtime import SimpleTool, discover_tool_names


def _call(query: str, **_kwargs):
    matches = [name for name in discover_tool_names() if query.casefold() in name.casefold()]
    return {'data': {'query': query, 'results': matches, 'count': len(matches)}}


ToolSearchTool = SimpleTool(
    name='ToolSearch',
    description_text='Search the available Python port tool packages by name.',
    prompt_text='Use to discover which tool modules are currently mirrored into the Python port.',
    call_handler=_call,
    input_schema={'query': 'tool search query'},
    output_schema={'results': 'matching tool package names'},
    user_facing_name='Tool Search',
)
