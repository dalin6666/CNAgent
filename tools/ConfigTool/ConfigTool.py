from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from .._runtime import ToolUseContext, persist_config, persist_settings
from .constants import CONFIG_TOOL_NAME
from .prompt import DESCRIPTION, generatePrompt
from .supportedSettings import (
    DEFAULT_GLOBAL_CONFIG,
    DEFAULT_SETTINGS,
    getConfig,
    getOptionsForSetting,
    getPath,
    isSupported,
)


def _json_stringify(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _get_nested_value(payload: dict[str, Any], path: list[str]) -> Any:
    current: Any = payload
    for key in path:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return None
    return current


def _set_nested_value(payload: dict[str, Any], path: list[str], value: Any) -> None:
    if not path:
        return
    current = payload
    for key in path[:-1]:
        child = current.get(key)
        if not isinstance(child, dict):
            child = {}
            current[key] = child
        current = child
    current[path[-1]] = value


def _delete_nested_value(payload: dict[str, Any], path: list[str]) -> None:
    if not path:
        return
    current = payload
    for key in path[:-1]:
        child = current.get(key)
        if not isinstance(child, dict):
            return
        current = child
    current.pop(path[-1], None)


def _merge_nested(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_nested(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _get_remote_control_at_startup(state: Any) -> bool:
    return bool((getattr(state, 'config', {}) or {}).get('remoteControlAtStartup', False))


def _sync_remote_bridge_state(state: Any) -> None:
    state.repl_bridge_enabled = _get_remote_control_at_startup(state)
    state.repl_bridge_outbound_only = False


def _sync_immediate_state(
    setting: str,
    value: Any,
    *,
    state: Any,
    toolUseContext: ToolUseContext | None,
) -> None:
    if toolUseContext is not None:
        if setting == 'verbose':
            toolUseContext.options.verbose = bool(value)
        elif setting == 'model' and value is not None:
            toolUseContext.options.main_loop_model = str(value)
        elif setting == 'alwaysThinkingEnabled':
            toolUseContext.options.thinking_config = {
                'type': 'enabled' if bool(value) else 'disabled'
            }
    if setting == 'remoteControlAtStartup':
        _sync_remote_bridge_state(state)


class PythonConfigTool:
    name = CONFIG_TOOL_NAME
    search_hint = 'get or set Claude Code settings (theme, model)'
    max_result_size_chars = 100_000
    should_defer = True
    input_schema = {
        'setting': 'configuration key',
        'value': 'optional value to set',
    }
    output_schema = {
        'success': 'whether the operation succeeded',
        'operation': 'get or set',
        'setting': 'the setting key',
        'value': 'current value for get operations',
        'previousValue': 'old value for set operations',
        'newValue': 'new value for set operations',
        'error': 'error message when unsuccessful',
    }

    async def description(self, _input_data: dict[str, Any] | None = None) -> str:
        return DESCRIPTION

    async def prompt(self) -> str:
        return generatePrompt()

    def userFacingName(self, _input_data: dict[str, Any] | None = None) -> str:
        return 'Config'

    def isConcurrencySafe(self, _input_data: dict[str, Any] | None = None) -> bool:
        return True

    def isReadOnly(self, input_data: dict[str, Any]) -> bool:
        return input_data.get('value') is None

    def toAutoClassifierInput(self, input_data: dict[str, Any]) -> str:
        if input_data.get('value') is None:
            return str(input_data.get('setting', ''))
        return f"{input_data.get('setting', '')} = {input_data.get('value')}"

    async def checkPermissions(
        self,
        input_data: dict[str, Any],
        _context: ToolUseContext | None = None,
    ) -> dict[str, Any]:
        if input_data.get('value') is None:
            return {'behavior': 'allow', 'updatedInput': input_data}
        return {
            'behavior': 'ask',
            'message': f"Set {input_data.get('setting')} to {_json_stringify(input_data.get('value'))}",
            'updatedInput': input_data,
        }

    async def call(
        self,
        *args: Any,
        setting: str | None = None,
        value: Any = None,
        toolUseContext: ToolUseContext | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        if args and isinstance(args[0], dict):
            payload = dict(args[0])
            setting = payload.get('setting', setting)
            value = payload.get('value', value)

        if not setting:
            return {'data': {'success': False, 'error': 'Setting name is required'}}

        if not isSupported(setting):
            return {'data': {'success': False, 'error': f'Unknown setting: "{setting}"'}}

        context = toolUseContext or ToolUseContext()
        state = context.getAppState()
        config = getConfig(setting)
        if config is None:
            return {'data': {'success': False, 'error': f'Unknown setting: "{setting}"'}}

        path = getPath(setting)
        source_payload = state.config if config.source == 'global' else state.settings
        effective_payload = (
            _merge_nested(DEFAULT_GLOBAL_CONFIG, state.config)
            if config.source == 'global'
            else _merge_nested(DEFAULT_SETTINGS, state.settings)
        )

        if value is None:
            current_value = _get_nested_value(effective_payload, path)
            display_value = (
                config.format_on_read(current_value)
                if config.format_on_read is not None
                else current_value
            )
            return {
                'data': {
                    'success': True,
                    'operation': 'get',
                    'setting': setting,
                    'value': display_value,
                }
            }

        if (
            setting == 'remoteControlAtStartup'
            and isinstance(value, str)
            and value.strip().lower() == 'default'
        ):
            previous_value = _get_nested_value(effective_payload, path)
            _delete_nested_value(state.config, path)
            persist_config(state)
            _sync_remote_bridge_state(state)
            return {
                'data': {
                    'success': True,
                    'operation': 'set',
                    'setting': setting,
                    'previousValue': previous_value,
                    'newValue': _get_remote_control_at_startup(state),
                }
            }

        final_value: Any = value

        if config.type == 'boolean':
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered == 'true':
                    final_value = True
                elif lowered == 'false':
                    final_value = False
            if not isinstance(final_value, bool):
                return {
                    'data': {
                        'success': False,
                        'operation': 'set',
                        'setting': setting,
                        'error': f'{setting} requires true or false.',
                    }
                }

        options = getOptionsForSetting(setting)
        if options and setting != 'model' and str(final_value) not in options:
            return {
                'data': {
                    'success': False,
                    'operation': 'set',
                    'setting': setting,
                    'error': f'Invalid value "{value}". Options: {", ".join(options)}',
                }
            }

        if config.validate_on_write is not None:
            validation = config.validate_on_write(final_value)
            if not validation.get('valid'):
                return {
                    'data': {
                        'success': False,
                        'operation': 'set',
                        'setting': setting,
                        'error': validation.get('error') or 'Validation failed',
                }
            }

        previous_value = deepcopy(_get_nested_value(effective_payload, path))

        try:
            _set_nested_value(source_payload, path, final_value)
            if config.source == 'global':
                persist_config(state)
            else:
                persist_settings(state)

            _sync_immediate_state(
                setting,
                final_value,
                state=state,
                toolUseContext=context,
            )

            return {
                'data': {
                    'success': True,
                    'operation': 'set',
                    'setting': setting,
                    'previousValue': previous_value,
                    'newValue': final_value,
                }
            }
        except Exception as exc:  # noqa: BLE001
            return {
                'data': {
                    'success': False,
                    'operation': 'set',
                    'setting': setting,
                    'error': str(exc),
                }
            }

    def mapToolResultToToolResultBlockParam(
        self,
        output: dict[str, Any],
        tool_use_id: str,
    ) -> dict[str, Any]:
        if output.get('success'):
            if output.get('operation') == 'get':
                return {
                    'tool_use_id': tool_use_id,
                    'type': 'tool_result',
                    'content': f"{output.get('setting')} = {_json_stringify(output.get('value'))}",
                }
            return {
                'tool_use_id': tool_use_id,
                'type': 'tool_result',
                'content': f"Set {output.get('setting')} to {_json_stringify(output.get('newValue'))}",
            }
        return {
            'tool_use_id': tool_use_id,
            'type': 'tool_result',
            'content': f"Error: {output.get('error')}",
            'is_error': True,
        }


ConfigTool = PythonConfigTool()

__all__ = ['ConfigTool', 'PythonConfigTool']
