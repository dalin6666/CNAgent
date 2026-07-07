from __future__ import annotations

from typing import Any

from .._runtime import SimpleTool


def _call(content: Any, **_kwargs) -> dict[str, Any]:
    return {'data': {'content': content}}


SyntheticOutputTool = SimpleTool(
    name='SyntheticOutput',
    description_text='Return synthetic output directly from the provided content.',
    prompt_text='Useful for tests or for mirroring synthetic tool results.',
    call_handler=_call,
    input_schema={'content': 'tool output payload'},
    output_schema={'content': 'echoed content'},
    user_facing_name='Synthetic Output',
)
