from __future__ import annotations

import os
from typing import Any

from .bashPermissions import bashPermissionRule, matchWildcardPattern
from .bashCommandHelpers import split_command_deprecated, strip_safe_wrappers


def _matches_rule(pattern: str, command: str) -> bool:
    rule = bashPermissionRule(pattern)
    normalized = strip_safe_wrappers(command).strip()
    if rule["type"] == "exact":
        return normalized == rule["command"]
    if rule["type"] == "prefix":
        return normalized == rule["prefix"] or normalized.startswith(rule["prefix"] + " ")
    return matchWildcardPattern(rule["pattern"], normalized)


def _contains_excluded_command(command: str, excluded_commands: list[str]) -> bool:
    if not excluded_commands:
        return False
    subcommands = split_command_deprecated(command) or [command]
    for subcommand in subcommands:
        if any(_matches_rule(pattern, subcommand) for pattern in excluded_commands):
            return True
    return False


def shouldUseSandbox(input_data: dict[str, Any]) -> bool:
    if bool(input_data.get("dangerouslyDisableSandbox")):
        return False
    enabled = os.environ.get("CLAUDE_CODE_ENABLE_SANDBOX", "").strip().lower() in {"1", "true", "yes"}
    sandbox_config = input_data.get("sandbox")
    if isinstance(sandbox_config, dict):
        enabled = bool(sandbox_config.get("enabled", enabled))
        excluded_commands = list(sandbox_config.get("excludedCommands", []))
    else:
        raw_excluded = os.environ.get("CLAUDE_CODE_SANDBOX_EXCLUDED_COMMANDS", "")
        excluded_commands = [item.strip() for item in raw_excluded.split(",") if item.strip()]
    command = str(input_data.get("command", ""))
    if not enabled or not command:
        return False
    if _contains_excluded_command(command, excluded_commands):
        return False
    return True


__all__ = ["shouldUseSandbox"]
