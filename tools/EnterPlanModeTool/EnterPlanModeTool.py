from __future__ import annotations

from typing import Any

from .._runtime import ToolUseContext, default_tool_permission_context
from .constants import ENTER_PLAN_MODE_TOOL_NAME
from .prompt import getEnterPlanModeToolPrompt, isPlanModeInterviewPhaseEnabled


def _handle_plan_mode_transition(state: Any, from_mode: str, to_mode: str) -> None:
    if to_mode == 'plan' and from_mode != 'plan':
        state.needs_plan_mode_exit_attachment = False
    if from_mode == 'plan' and to_mode != 'plan':
        state.needs_plan_mode_exit_attachment = True


def _apply_permission_update(
    permission_context: dict[str, Any],
    update: dict[str, Any],
) -> dict[str, Any]:
    updated = dict(permission_context)
    if update.get('type') == 'setMode':
        updated['mode'] = update.get('mode', updated.get('mode', 'default'))
    return updated


def _prepare_context_for_plan_mode(permission_context: dict[str, Any]) -> dict[str, Any]:
    updated = dict(permission_context)
    current_mode = str(updated.get('mode', 'default'))
    updated.setdefault('additionalWorkingDirectories', {})
    if current_mode == 'plan':
        return updated
    updated['prePlanMode'] = current_mode
    return updated


class PythonEnterPlanModeTool:
    name = ENTER_PLAN_MODE_TOOL_NAME
    search_hint = 'switch to plan mode to design an approach before coding'
    max_result_size_chars = 100_000
    should_defer = True
    input_schema: dict[str, Any] = {}
    output_schema = {
        'message': 'confirmation that plan mode was entered',
    }

    async def description(self, _input_data: dict[str, Any] | None = None) -> str:
        return (
            'Requests permission to enter plan mode for complex tasks requiring '
            'exploration and design'
        )

    async def prompt(self) -> str:
        return getEnterPlanModeToolPrompt()

    def userFacingName(self, _input_data: dict[str, Any] | None = None) -> str:
        return ''

    def isEnabled(self, context: ToolUseContext | None = None) -> bool:
        if context is None:
            return True
        state = context.getAppState()
        return len(getattr(state, 'allowed_channels', [])) == 0

    def isConcurrencySafe(self, _input_data: dict[str, Any] | None = None) -> bool:
        return True

    def isReadOnly(self, _input_data: dict[str, Any] | None = None) -> bool:
        return True

    def requiresUserInteraction(self) -> bool:
        return True

    async def checkPermissions(
        self,
        input_data: dict[str, Any],
        _context: ToolUseContext | None = None,
    ) -> dict[str, Any]:
        return {
            'behavior': 'ask',
            'message': 'Enter plan mode?',
            'updatedInput': input_data,
        }

    async def call(
        self,
        *args: Any,
        toolUseContext: ToolUseContext | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        del args
        context = toolUseContext or ToolUseContext()
        if context.agent_id:
            raise ValueError('EnterPlanMode tool cannot be used in agent contexts')
        if not self.isEnabled(context):
            raise ValueError('EnterPlanMode is unavailable while channels are enabled')

        state = context.getAppState()
        current_permission_context = dict(
            getattr(state, 'tool_permission_context', None)
            or default_tool_permission_context()
        )
        from_mode = str(current_permission_context.get('mode', 'default'))
        _handle_plan_mode_transition(state, from_mode, 'plan')

        updated_permission_context = _apply_permission_update(
            _prepare_context_for_plan_mode(current_permission_context),
            {'type': 'setMode', 'mode': 'plan', 'destination': 'session'},
        )
        state.tool_permission_context = updated_permission_context
        state.config['toolPermissionContext'] = dict(updated_permission_context)
        state.plan_mode = True

        return {
            'data': {
                'message': (
                    'Entered plan mode. You should now focus on exploring the '
                    'codebase and designing an implementation approach.'
                )
            }
        }

    def mapToolResultToToolResultBlockParam(
        self,
        output: dict[str, Any],
        tool_use_id: str,
    ) -> dict[str, Any]:
        message = str(output.get('message', 'Entered plan mode.'))
        if isPlanModeInterviewPhaseEnabled():
            instructions = (
                message
                + '\n\nDO NOT write or edit any files except the plan file. '
                'Detailed workflow instructions will follow.'
            )
        else:
            instructions = (
                message
                + '\n\nIn plan mode, you should:\n'
                '1. Thoroughly explore the codebase to understand existing patterns\n'
                '2. Identify similar features and architectural approaches\n'
                '3. Consider multiple approaches and their trade-offs\n'
                '4. Use AskUserQuestion if you need to clarify the approach\n'
                '5. Design a concrete implementation strategy\n'
                '6. When ready, use ExitPlanMode to present your plan for approval\n\n'
                'Remember: DO NOT write or edit any files yet. This is a read-only '
                'exploration and planning phase.'
            )
        return {
            'type': 'tool_result',
            'content': instructions,
            'tool_use_id': tool_use_id,
        }


EnterPlanModeTool = PythonEnterPlanModeTool()

__all__ = ['EnterPlanModeTool', 'PythonEnterPlanModeTool']
