from __future__ import annotations

from .._runtime import SimpleTool, ToolUseContext


def _call(id: str, toolUseContext: ToolUseContext | None = None, **_kwargs):
    state = toolUseContext.getAppState() if toolUseContext else None
    task = (state.tasks if state is not None else {}).get(id)
    return {'data': {'task': task}}


TaskGetTool = SimpleTool(
    name='TaskGet',
    description_text='Fetch a single task from shared state.',
    prompt_text='Provide the task id returned by TaskCreateTool.',
    call_handler=_call,
    input_schema={'id': 'task identifier'},
    output_schema={'task': 'task payload'},
    user_facing_name='Task Get',
)
