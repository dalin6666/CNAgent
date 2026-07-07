from __future__ import annotations

from typing import Any

from .._runtime import SimpleTool, ToolUseContext, append_task_output, now_ms


def _call(id: str, status: str | None = None, description: str | None = None, subject: str | None = None, metadata: dict[str, Any] | None = None, output: str | None = None, toolUseContext: ToolUseContext | None = None, **_kwargs: Any):
    state = toolUseContext.getAppState() if toolUseContext else None
    task = (state.tasks if state is not None else {}).get(id)
    if task is None:
        return {'data': {'task': None}}
    if status is not None:
        task['status'] = status
    if description is not None:
        task['description'] = description
    if subject is not None:
        task['subject'] = subject
    if metadata:
        task.setdefault('metadata', {}).update(metadata)
    if output:
        append_task_output(id, output)
    task['updatedAt'] = now_ms()
    return {'data': {'task': task}}


TaskUpdateTool = SimpleTool(
    name='TaskUpdate',
    description_text='Update an existing task record.',
    prompt_text='Use to change status, metadata, or append output to a task.',
    call_handler=_call,
    input_schema={'id': 'task identifier', 'status': 'optional new status'},
    output_schema={'task': 'updated task payload'},
    user_facing_name='Task Update',
)
