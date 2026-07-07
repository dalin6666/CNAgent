from __future__ import annotations

from .._runtime import SimpleTool


def _call(tool_name: str, decision: str = 'allow', **_kwargs):
    return {'data': {'toolName': tool_name, 'decision': decision}}


TestingPermissionTool = SimpleTool(
    name='TestingPermission',
    description_text='Return a synthetic permission decision for tests.',
    prompt_text='Use only in tests that need a deterministic permission-tool response.',
    call_handler=_call,
    input_schema={'tool_name': 'tool name to simulate', 'decision': 'allow/deny/ask'},
    output_schema={'decision': 'returned decision'},
    user_facing_name='Testing Permission',
)
