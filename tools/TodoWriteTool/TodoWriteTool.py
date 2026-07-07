from __future__ import annotations

from typing import Any

from .._runtime import SimpleTool, ToolUseContext


def _call(todos: list[dict[str, Any]], toolUseContext: ToolUseContext | None = None, **_kwargs):
    state = toolUseContext.getAppState() if toolUseContext else None
    todo_key = toolUseContext.agent_id if toolUseContext and toolUseContext.agent_id else 'session'
    old_todos = list((state.todos if state is not None else {}).get(todo_key, []))
    if state is not None:
        state.todos[todo_key] = list(todos)
    return {'data': {'oldTodos': old_todos, 'newTodos': list(todos), 'verificationNudgeNeeded': False}}


TodoWriteTool = SimpleTool(
    name='TodoWrite',
    description_text='Replace the active todo list for the current session or agent.',
    prompt_text='Provide the full todo list you want to store.',
    call_handler=_call,
    input_schema={'todos': 'list of todo items'},
    output_schema={'oldTodos': 'previous list', 'newTodos': 'new list'},
    user_facing_name='Todo',
)
