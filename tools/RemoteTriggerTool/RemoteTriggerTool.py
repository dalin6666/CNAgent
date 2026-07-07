from __future__ import annotations

from typing import Any

from .._runtime import SimpleTool, ToolUseContext, create_id, now_ms, persist_remote_triggers


def _call(prompt: str, description: str | None = None, toolUseContext: ToolUseContext | None = None, **_kwargs: Any) -> dict[str, Any]:
    state = toolUseContext.getAppState() if toolUseContext else None
    trigger_id = create_id('remote_')
    record = {'id': trigger_id, 'prompt': prompt, 'description': description or prompt, 'createdAt': now_ms()}
    if state is not None:
        state.remote_triggers[trigger_id] = record
        persist_remote_triggers(state)
    return {'data': record}


RemoteTriggerTool = SimpleTool(
    name='RemoteTrigger',
    description_text='Record a remote trigger request in the Python port state.',
    prompt_text='Use when a workflow wants to hand off work to an external or deferred executor.',
    call_handler=_call,
    input_schema={'prompt': 'remote prompt', 'description': 'optional label'},
    output_schema={'id': 'trigger identifier'},
    user_facing_name='Remote Trigger',
)
