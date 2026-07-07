from __future__ import annotations

from .._runtime import SimpleTool, ToolUseContext


def _call(toolUseContext: ToolUseContext | None = None, **_kwargs):
    state = toolUseContext.getAppState() if toolUseContext else None
    tasks = list((state.cron_tasks if state is not None else {}).values())
    return {'data': {'tasks': tasks, 'count': len(tasks)}}


CronListTool = SimpleTool(
    name='CronList',
    description_text='List cron entries stored in the Python port state.',
    prompt_text='Use to inspect currently stored cron jobs.',
    call_handler=_call,
    output_schema={'tasks': 'cron records'},
    user_facing_name='Cron List',
)
