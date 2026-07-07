from __future__ import annotations

from .._runtime import SimpleTool, ToolUseContext


def _call(status: str | None = None, toolUseContext: ToolUseContext | None = None, **_kwargs):
    state = toolUseContext.getAppState() if toolUseContext else None
    tasks = list((state.tasks if state is not None else {}).values())
    if status is not None:
        tasks = [task for task in tasks if task.get('status') == status]
    return {'data': {'tasks': tasks, 'count': len(tasks)}}


TaskListTool = SimpleTool(
    name='TaskList',
    description_text='List tasks from shared state.',
    prompt_text='Optionally filter by task status.',
    call_handler=_call,
    input_schema={'status': 'optional task status filter'},
    output_schema={'tasks': 'task list'},
    user_facing_name='Task List',
)
