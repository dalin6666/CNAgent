from __future__ import annotations

from pathlib import Path

from .._runtime import SimpleTool, ToolUseContext, get_task_output_path


def _call(task_id: str, block: bool = True, timeout: int = 30_000, toolUseContext: ToolUseContext | None = None, **_kwargs):
    del block, timeout
    state = toolUseContext.getAppState() if toolUseContext else None
    task = (state.tasks if state is not None else {}).get(task_id)
    if task is None:
        return {'data': {'retrieval_status': 'not_ready', 'task': None}}
    output_path = Path(task.get('outputFile') or get_task_output_path(task_id))
    output = output_path.read_text(encoding='utf-8', errors='replace') if output_path.exists() else ''
    task_payload = dict(task)
    task_payload['output'] = output
    return {'data': {'retrieval_status': 'success', 'task': task_payload}}


TaskOutputTool = SimpleTool(
    name='TaskOutput',
    description_text='Read the captured output for a task.',
    prompt_text='Use with a task id previously created by TaskCreateTool or AgentTool.',
    call_handler=_call,
    input_schema={'task_id': 'task identifier'},
    output_schema={'task': 'task plus output contents'},
    user_facing_name='Task Output',
)
