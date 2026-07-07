from __future__ import annotations

from .supportedSettings import SUPPORTED_SETTINGS, getModelOptions, getOptionsForSetting


DESCRIPTION = 'Get or set Claude Code configuration settings.'


def generatePrompt() -> str:
    global_settings: list[str] = []
    project_settings: list[str] = []

    for key, config in SUPPORTED_SETTINGS.items():
        if key == 'model':
            continue

        options = getOptionsForSetting(key)
        line = f'- {key}'
        if options:
            line += ': ' + ', '.join(f'"{option}"' for option in options)
        elif config.type == 'boolean':
            line += ': true/false'
        line += f' - {config.description}'

        if config.source == 'global':
            global_settings.append(line)
        else:
            project_settings.append(line)

    model_section = _generate_model_section()

    return f"""Get or set Claude Code configuration settings.

View or change Claude Code settings. Use when the user requests configuration changes, asks about current settings, or when adjusting a setting would benefit them.

## Usage
- Get current value: omit the "value" parameter
- Set new value: include the "value" parameter

## Configurable settings list
The following settings are available for you to change:

### Global Settings (stored in global config)
{chr(10).join(global_settings)}

### Project Settings (stored in user settings)
{chr(10).join(project_settings)}

{model_section}
## Examples
- Get theme: {{ "setting": "theme" }}
- Set dark theme: {{ "setting": "theme", "value": "dark" }}
- Enable vim mode: {{ "setting": "editorMode", "value": "vim" }}
- Enable verbose: {{ "setting": "verbose", "value": true }}
- Change model: {{ "setting": "model", "value": "opus" }}
- Change permission mode: {{ "setting": "permissions.defaultMode", "value": "plan" }}
"""


def _generate_model_section() -> str:
    options = getModelOptions()
    if not options:
        return (
            '## Model\n'
            '- model - Override the default model (sonnet, opus, haiku, or a full model ID)'
        )
    lines = []
    for option in options:
        value = 'null/"default"' if option.get('value') is None else f'"{option["value"]}"'
        description = option.get('descriptionForModel') or option.get('description') or ''
        lines.append(f'  - {value}: {description}')
    return '## Model\n- model - Override the default model. Available options:\n' + '\n'.join(lines)


__all__ = ['DESCRIPTION', 'generatePrompt']
