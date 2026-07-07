from __future__ import annotations

from .bashCommandHelpers import split_command_deprecated


ACCEPT_EDITS_ALLOWED_COMMANDS = ["mkdir", "touch", "rm", "rmdir", "mv", "cp", "sed"]


def _validateCommandForMode(
    cmd: str,
    toolPermissionContext: dict[str, object] | None,
) -> dict[str, object]:
    mode = str((toolPermissionContext or {}).get("mode", "default"))
    base_cmd = (cmd.strip().split() or [""])[0]
    if not base_cmd:
        return {"behavior": "passthrough", "message": "Base command not found"}
    if mode == "acceptEdits" and base_cmd in ACCEPT_EDITS_ALLOWED_COMMANDS:
        return {
            "behavior": "allow",
            "updatedInput": {"command": cmd},
            "decisionReason": {"type": "mode", "mode": "acceptEdits"},
        }
    return {"behavior": "passthrough", "message": f"No mode-specific handling for {base_cmd}"}


def checkPermissionMode(
    input_data: dict[str, object],
    toolPermissionContext: dict[str, object] | None,
) -> dict[str, object]:
    mode = str((toolPermissionContext or {}).get("mode", "default"))
    if mode in {"bypassPermissions", "dontAsk"}:
        return {"behavior": "passthrough", "message": f"{mode} mode handled elsewhere"}
    for cmd in split_command_deprecated(str(input_data.get("command", ""))):
        result = _validateCommandForMode(cmd, toolPermissionContext)
        if result.get("behavior") != "passthrough":
            return result
    return {"behavior": "passthrough", "message": "No mode-specific validation required"}


def getAutoAllowedCommands(mode: str) -> tuple[str, ...]:
    return tuple(ACCEPT_EDITS_ALLOWED_COMMANDS) if mode == "acceptEdits" else ()


__all__ = ["checkPermissionMode", "getAutoAllowedCommands"]
