from __future__ import annotations

from .._runtime import SimpleTool, ToolUseContext, persist_cron_tasks


def _call(id: str, toolUseContext: ToolUseContext | None = None, **_kwargs):
    state = toolUseContext.getAppState() if toolUseContext else None
    removed = None
    if state is not None:
        removed = state.cron_tasks.pop(id, None)
        persist_cron_tasks(state)
    return {'data': {'id': id, 'deleted': removed is not None}}


CronDeleteTool = SimpleTool(
    name='CronDelete',
    description_text='Delete a scheduled cron entry from the Python port state.',
    prompt_text='Provide the cron job id previously returned by CronCreateTool.',
    call_handler=_call,
    input_schema={'id': 'cron identifier'},
    output_schema={'deleted': 'whether the job was deleted'},
    user_facing_name='Cron Delete',
)
