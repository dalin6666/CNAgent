from __future__ import annotations

from typing import Any

from .._runtime import SimpleTool, ToolUseContext, create_id


def _call(name: str, members: list[str] | None = None, description: str | None = None, toolUseContext: ToolUseContext | None = None, **_kwargs: Any):
    state = toolUseContext.getAppState() if toolUseContext else None
    team_id = create_id('team_')
    team = {'id': team_id, 'name': name, 'members': members or [], 'description': description}
    if state is not None:
        state.teams[team_id] = team
    return {'data': {'team': team}}


TeamCreateTool = SimpleTool(
    name='TeamCreate',
    description_text='Create a named team record in shared state.',
    prompt_text='Provide a team name and an optional member list.',
    call_handler=_call,
    input_schema={'name': 'team name', 'members': 'optional member names'},
    output_schema={'team': 'new team payload'},
    user_facing_name='Team Create',
)
