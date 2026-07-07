from __future__ import annotations

from .._runtime import SimpleTool, ToolUseContext


def _call(id: str | None = None, name: str | None = None, toolUseContext: ToolUseContext | None = None, **_kwargs):
    state = toolUseContext.getAppState() if toolUseContext else None
    if state is None:
        return {'data': {'deleted': False}}
    removed = None
    if id is not None:
        removed = state.teams.pop(id, None)
    elif name is not None:
        for team_id, payload in list(state.teams.items()):
            if payload.get('name') == name:
                removed = state.teams.pop(team_id)
                break
    return {'data': {'deleted': removed is not None, 'team': removed}}


TeamDeleteTool = SimpleTool(
    name='TeamDelete',
    description_text='Delete a team record from shared state.',
    prompt_text='Provide either the team id or the team name.',
    call_handler=_call,
    input_schema={'id': 'team identifier', 'name': 'team name'},
    output_schema={'deleted': 'whether a team was removed'},
    user_facing_name='Team Delete',
)
