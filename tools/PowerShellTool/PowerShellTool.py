from __future__ import annotations

from typing import Any

from .._runtime import SimpleTool, ToolUseContext, expand_path, run_subprocess


def _call(command: str, cwd: str | None = None, timeout_ms: int = 30_000, env: dict[str, str] | None = None, toolUseContext: ToolUseContext | None = None, **_kwargs: Any) -> dict[str, Any]:
    effective_cwd = expand_path(cwd, toolUseContext.options.cwd if toolUseContext else None) if cwd else toolUseContext.options.cwd if toolUseContext else None
    return {'data': run_subprocess(command, cwd=effective_cwd, timeout_ms=timeout_ms, shell_type='powershell', env=env)}


PowerShellTool = SimpleTool(
    name='PowerShell',
    description_text='Run a PowerShell command locally.',
    prompt_text='Use for Windows-native shell operations and PowerShell scripts.',
    call_handler=_call,
    input_schema={'command': 'PowerShell command', 'cwd': 'optional working directory'},
    output_schema={'code': 'process exit code', 'stdout': 'standard output', 'stderr': 'standard error'},
    user_facing_name='PowerShell',
)
