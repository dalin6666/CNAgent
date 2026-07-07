from __future__ import annotations

from typing import Any

from .._runtime import SimpleTool, ToolUseContext, create_id, now_ms, persist_cron_tasks


def _call(cron: str, prompt: str, recurring: bool = True, durable: bool = False, toolUseContext: ToolUseContext | None = None, **_kwargs: Any) -> dict[str, Any]:
    state = toolUseContext.getAppState() if toolUseContext else None
    task_id = create_id('cron_')
    record = {'id': task_id, 'cron': cron, 'prompt': prompt, 'recurring': recurring, 'durable': durable, 'createdAt': now_ms()}
    if state is not None:
        state.cron_tasks[task_id] = record
        persist_cron_tasks(state)
    return {'data': {'id': task_id, 'humanSchedule': cron, 'recurring': recurring, 'durable': durable}}


CronCreateTool = SimpleTool(
    name='CronCreate',
    description_text='Create a scheduled cron entry in the Python port state.',
    prompt_text='Provide a cron expression plus the prompt that should run on each trigger.',
    call_handler=_call,
    input_schema={'cron': 'cron expression', 'prompt': 'scheduled prompt'},
    output_schema={'id': 'cron identifier'},
    user_facing_name='Cron Create',
)
