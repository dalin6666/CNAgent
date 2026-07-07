from __future__ import annotations

from typing import Any

from .._runtime import SimpleTool, ToolUseContext, create_id, get_task_output_path, now_ms, write_text_file


def _call(subject: str, description: str, activeForm: str | None = None, metadata: dict[str, Any] | None = None, toolUseContext: ToolUseContext | None = None, **_kwargs: Any) -> dict[str, Any]:
    state = toolUseContext.getAppState() if toolUseContext else None
    task_id = create_id('task_')
    task = {'id': task_id, 'subject': subject, 'description': description, 'activeForm': activeForm, 'metadata': metadata or {}, 'status': 'pending', 'createdAt': now_ms(), 'outputFile': get_task_output_path(task_id)}
    write_text_file(task['outputFile'], '')
    if state is not None:
        state.tasks[task_id] = task
    return {'data': {'task': {'id': task_id, 'subject': subject}, 'outputFile': task['outputFile']}}


TaskCreateTool = SimpleTool(
    name='TaskCreate',
    description_text='Create a task record in shared state.',
    prompt_text='Use to register a pending task that can later be updated or queried.',
    call_handler=_call,
    input_schema={'subject': 'task title', 'description': 'task description'},
    output_schema={'task': 'new task summary'},
    user_facing_name='Task Create',
)
