from __future__ import annotations

from typing import Any

from .._runtime import SimpleTool, ToolUseContext, create_id, now_ms


def _call(target: str, message: str, metadata: dict[str, Any] | None = None, toolUseContext: ToolUseContext | None = None, **_kwargs: Any) -> dict[str, Any]:
    state = toolUseContext.getAppState() if toolUseContext else None
    payload = {'id': create_id('msg_'), 'message': message, 'metadata': metadata or {}, 'createdAt': now_ms()}
    if state is not None:
        state.mailboxes.setdefault(target, []).append(payload)
    return {'data': {'target': target, 'message': payload}}


SendMessageTool = SimpleTool(
    name='SendMessage',
    description_text='Append a message to a target mailbox in the shared app state.',
    prompt_text='Use for inter-agent or inter-task coordination inside the Python port runtime.',
    call_handler=_call,
    input_schema={'target': 'mailbox name or task id', 'message': 'message content'},
    output_schema={'message': 'stored message payload'},
    user_facing_name='Send Message',
)
