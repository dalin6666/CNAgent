from __future__ import annotations

from .._runtime import SimpleTool, ToolUseContext


def _call(task_id: str, toolUseContext: ToolUseContext | None = None, **_kwargs):
    state = toolUseContext.getAppState() if toolUseContext else None
    task = (state.tasks if state is not None else {}).get(task_id)
    if task is None:
        return {'data': {'task_id': task_id, 'stopped': False}}
    task['status'] = 'stopped'
    return {'data': {'task_id': task_id, 'stopped': True}}


TaskStopTool = SimpleTool(
    name='TaskStop',
    description_text='Mark a task as stopped.',
    prompt_text='Use when a background task should no longer be considered active.',
    call_handler=_call,
    input_schema={'task_id': 'task identifier'},
    output_schema={'stopped': 'whether the task was stopped'},
    user_facing_name='Task Stop',
)
