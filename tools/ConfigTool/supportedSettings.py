from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Literal


SourceName = Literal['global', 'settings']
SettingType = Literal['boolean', 'string']
SyncableAppStateKey = Literal['verbose', 'mainLoopModel', 'thinkingEnabled']


def _env_truthy(name: str) -> bool:
    value = os.getenv(name, '')
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def _voice_mode_available() -> bool:
    return _env_truthy('CLAUDE_CODE_ENABLE_VOICE') or _env_truthy('VOICE_MODE')


def _bridge_mode_available() -> bool:
    return _env_truthy('CLAUDE_CODE_ENABLE_BRIDGE') or _env_truthy('BRIDGE_MODE')


def _push_notifications_available() -> bool:
    return (
        _env_truthy('CLAUDE_CODE_ENABLE_PUSH_NOTIFICATIONS')
        or _env_truthy('KAIROS')
        or _env_truthy('KAIROS_PUSH_NOTIFICATION')
    )


NOTIFICATION_CHANNELS = (
    'auto',
    'iterm2',
    'iterm2_with_bell',
    'terminal_bell',
    'kitty',
    'ghostty',
    'notifications_disabled',
)
EDITOR_MODES = ('normal', 'vim')
TEAMMATE_MODES = ('auto', 'tmux', 'in-process')
THEME_NAMES = (
    'dark',
    'light',
    'light-daltonized',
    'dark-daltonized',
    'light-ansi',
    'dark-ansi',
)
THEME_SETTINGS = ('auto', *THEME_NAMES)

DEFAULT_GLOBAL_CONFIG: dict[str, Any] = {
    'theme': 'dark',
    'preferredNotifChannel': 'auto',
    'verbose': False,
    'editorMode': 'normal',
    'autoCompactEnabled': True,
    'showTurnDuration': True,
    'todoFeatureEnabled': True,
    'fileCheckpointingEnabled': True,
    'terminalProgressBarEnabled': True,
}
DEFAULT_SETTINGS: dict[str, Any] = {
    'permissions': {
        'defaultMode': 'default',
    }
}


@dataclass(frozen=True)
class SettingConfig:
    source: SourceName
    type: SettingType
    description: str
    path: tuple[str, ...] | None = None
    options: tuple[str, ...] | None = None
    get_options: Callable[[], list[str]] | None = None
    app_state_key: SyncableAppStateKey | None = None
    validate_on_write: Callable[[Any], dict[str, Any]] | None = None
    format_on_read: Callable[[Any], Any] | None = None


def getModelOptions(fastMode: bool = False) -> list[dict[str, Any]]:
    del fastMode
    options = [
        {
            'value': None,
            'label': 'Default (recommended)',
            'description': 'Use the default model for this session.',
            'descriptionForModel': 'Default model chosen by the runtime.',
        },
        {
            'value': 'sonnet',
            'label': 'Sonnet',
            'description': 'Balanced model for most coding tasks.',
            'descriptionForModel': 'Balanced model for everyday coding work.',
        },
        {
            'value': 'opus',
            'label': 'Opus',
            'description': 'Most capable option for complex work.',
            'descriptionForModel': 'Most capable option for complex work.',
        },
        {
            'value': 'haiku',
            'label': 'Haiku',
            'description': 'Fastest option for lightweight tasks.',
            'descriptionForModel': 'Fastest option for lightweight tasks.',
        },
        {
            'value': 'opusplan',
            'label': 'Opus Plan Mode',
            'description': 'Use Opus in plan mode and Sonnet otherwise.',
            'descriptionForModel': 'Use Opus in plan mode and Sonnet otherwise.',
        },
    ]
    custom_model = os.getenv('ANTHROPIC_CUSTOM_MODEL_OPTION')
    if custom_model and not any(option['value'] == custom_model for option in options):
        options.append(
            {
                'value': custom_model,
                'label': os.getenv('ANTHROPIC_CUSTOM_MODEL_OPTION_NAME', custom_model),
                'description': os.getenv(
                    'ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION',
                    f'Custom model ({custom_model})',
                ),
                'descriptionForModel': os.getenv(
                    'ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION',
                    f'Custom model ({custom_model})',
                ),
            }
        )
    return options


def _model_option_values() -> list[str]:
    return [
        str(option['value'])
        for option in getModelOptions()
        if option.get('value') is not None
    ]


def _validate_model(value: Any) -> dict[str, Any]:
    normalized = str(value).strip()
    if not normalized:
        return {'valid': False, 'error': 'Model name cannot be empty'}
    if normalized in _model_option_values():
        return {'valid': True}
    if re.fullmatch(r'[A-Za-z0-9._:/-]+(?:\[[A-Za-z0-9_-]+\])?', normalized):
        return {'valid': True}
    return {
        'valid': False,
        'error': f"Model '{normalized}' is not a recognized alias or model identifier",
    }


SUPPORTED_SETTINGS: dict[str, SettingConfig] = {
    'theme': SettingConfig(
        source='global',
        type='string',
        description='Color theme for the UI',
        options=THEME_SETTINGS,
    ),
    'editorMode': SettingConfig(
        source='global',
        type='string',
        description='Key binding mode',
        options=EDITOR_MODES,
    ),
    'verbose': SettingConfig(
        source='global',
        type='boolean',
        description='Show detailed debug output',
        app_state_key='verbose',
    ),
    'preferredNotifChannel': SettingConfig(
        source='global',
        type='string',
        description='Preferred notification channel',
        options=NOTIFICATION_CHANNELS,
    ),
    'autoCompactEnabled': SettingConfig(
        source='global',
        type='boolean',
        description='Auto-compact when context is full',
    ),
    'autoMemoryEnabled': SettingConfig(
        source='settings',
        type='boolean',
        description='Enable auto-memory',
    ),
    'autoDreamEnabled': SettingConfig(
        source='settings',
        type='boolean',
        description='Enable background memory consolidation',
    ),
    'fileCheckpointingEnabled': SettingConfig(
        source='global',
        type='boolean',
        description='Enable file checkpointing for code rewind',
    ),
    'showTurnDuration': SettingConfig(
        source='global',
        type='boolean',
        description='Show turn duration message after responses',
    ),
    'terminalProgressBarEnabled': SettingConfig(
        source='global',
        type='boolean',
        description='Show OSC 9;4 progress indicator in supported terminals',
    ),
    'todoFeatureEnabled': SettingConfig(
        source='global',
        type='boolean',
        description='Enable todo/task tracking',
    ),
    'model': SettingConfig(
        source='settings',
        type='string',
        description='Override the default model',
        app_state_key='mainLoopModel',
        get_options=_model_option_values,
        validate_on_write=_validate_model,
        format_on_read=lambda value: 'default' if value is None else value,
    ),
    'alwaysThinkingEnabled': SettingConfig(
        source='settings',
        type='boolean',
        description='Enable extended thinking (false to disable)',
        app_state_key='thinkingEnabled',
    ),
    'permissions.defaultMode': SettingConfig(
        source='settings',
        type='string',
        description='Default permission mode for tool usage',
        options=('default', 'plan', 'acceptEdits', 'dontAsk', 'auto'),
    ),
    'language': SettingConfig(
        source='settings',
        type='string',
        description='Preferred language for Claude responses and dictation',
    ),
    'teammateMode': SettingConfig(
        source='global',
        type='string',
        description='How to spawn teammates',
        options=TEAMMATE_MODES,
    ),
}

if os.getenv('USER_TYPE') == 'ant':
    SUPPORTED_SETTINGS['classifierPermissionsEnabled'] = SettingConfig(
        source='settings',
        type='boolean',
        description='Enable AI-based classification for Bash(prompt:...) rules',
    )

if _voice_mode_available():
    SUPPORTED_SETTINGS['voiceEnabled'] = SettingConfig(
        source='settings',
        type='boolean',
        description='Enable voice dictation (hold-to-talk)',
    )

if _bridge_mode_available():
    SUPPORTED_SETTINGS['remoteControlAtStartup'] = SettingConfig(
        source='global',
        type='boolean',
        description='Enable Remote Control for all sessions (true | false | default)',
        format_on_read=lambda value: bool(value) if value is not None else False,
    )

if _push_notifications_available():
    SUPPORTED_SETTINGS.update(
        {
            'taskCompleteNotifEnabled': SettingConfig(
                source='global',
                type='boolean',
                description='Push when Claude finishes while you are idle',
            ),
            'inputNeededNotifEnabled': SettingConfig(
                source='global',
                type='boolean',
                description='Push when a permission prompt or question is waiting',
            ),
            'agentPushNotifEnabled': SettingConfig(
                source='global',
                type='boolean',
                description='Allow Claude to push when it deems it appropriate',
            ),
        }
    )


def isSupported(key: str) -> bool:
    return key in SUPPORTED_SETTINGS


def getConfig(key: str) -> SettingConfig | None:
    return SUPPORTED_SETTINGS.get(key)


def getAllKeys() -> list[str]:
    return list(SUPPORTED_SETTINGS)


def getOptionsForSetting(key: str) -> list[str] | None:
    config = SUPPORTED_SETTINGS.get(key)
    if config is None:
        return None
    if config.options is not None:
        return list(config.options)
    if config.get_options is not None:
        return list(config.get_options())
    return None


def getPath(key: str) -> list[str]:
    config = SUPPORTED_SETTINGS.get(key)
    if config is None or config.path is None:
        return key.split('.')
    return list(config.path)


__all__ = [
    'DEFAULT_GLOBAL_CONFIG',
    'DEFAULT_SETTINGS',
    'EDITOR_MODES',
    'NOTIFICATION_CHANNELS',
    'SUPPORTED_SETTINGS',
    'TEAMMATE_MODES',
    'THEME_NAMES',
    'THEME_SETTINGS',
    'SettingConfig',
    'getAllKeys',
    'getConfig',
    'getModelOptions',
    'getOptionsForSetting',
    'getPath',
    'isSupported',
]
