from __future__ import annotations

import re
import shlex
from typing import Any

from .bashCommandHelpers import split_command_deprecated, strip_safe_wrappers
from .bashSecurity import bashCommandIsSafe_DEPRECATED
from .sedValidation import sedCommandIsAllowedByAllowlist


READONLY_COMMANDS = {
    "ls",
    "find",
    "grep",
    "rg",
    "cat",
    "head",
    "tail",
    "less",
    "more",
    "wc",
    "stat",
    "file",
    "strings",
    "jq",
    "awk",
    "cut",
    "sort",
    "uniq",
    "tr",
    "pwd",
    "which",
    "whereis",
    "whoami",
    "arch",
    "history",
    "alias",
    "ps",
    "netstat",
    "ifconfig",
    "ip",
    "sha256sum",
    "sha1sum",
    "md5sum",
    "diff",
    "test",
    "[",
    "base64",
    "column",
    "nl",
    "hexdump",
    "od",
}

GIT_READONLY_SUBCOMMANDS = {
    "status",
    "diff",
    "show",
    "log",
    "rev-parse",
    "branch",
    "tag",
    "remote",
    "config",
    "ls-files",
    "blame",
    "grep",
}


def _contains_unquoted_expansion(command: str) -> bool:
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(command):
        if escaped:
            escaped = False
            continue
        if char == "\\" and not in_single:
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if in_single:
            continue
        if char == "$":
            next_char = command[index + 1] if index + 1 < len(command) else ""
            if next_char and re.match(r"[A-Za-z_@*#?!$0-9-]", next_char):
                return True
        if in_double:
            continue
        if char in "?*[]":
            return True
    return False


def _is_git_read_only(tokens: list[str], command: str) -> bool:
    if len(tokens) < 2:
        return False
    if re.search(r"\s-c[\s=]|\s--exec-path[\s=]|\s--config-env[\s=]", command):
        return False
    subcommand = tokens[1]
    if subcommand == "config":
        return "--get" in tokens or "--global" not in tokens
    return subcommand in GIT_READONLY_SUBCOMMANDS


def isCommandSafeViaFlagParsing(command: str) -> bool:
    return isCommandReadOnly(command)


def isCommandReadOnly(command: str) -> bool:
    test_command = command.strip()
    if test_command.endswith(" 2>&1"):
        test_command = test_command[:-5].strip()
    if _contains_unquoted_expansion(test_command):
        return False
    stripped = strip_safe_wrappers(test_command)
    try:
        tokens = shlex.split(stripped, posix=True)
    except ValueError:
        return False
    if not tokens:
        return False
    base = tokens[0]
    if base == "sed":
        return sedCommandIsAllowedByAllowlist(stripped, {"allowFileWrites": False})
    if base == "git":
        return _is_git_read_only(tokens, stripped)
    if base in {"python", "python3"}:
        return tokens[1:] in (["--version"], ["-V"])
    if base == "node":
        return tokens[1:] in (["--version"], ["-v"])
    if base in READONLY_COMMANDS:
        return True
    return False


def checkReadOnlyConstraints(
    input_data: dict[str, Any],
    compoundCommandHasCd: bool,
) -> dict[str, Any]:
    command = str(input_data.get("command", ""))
    security_result = bashCommandIsSafe_DEPRECATED(command)
    if security_result.get("behavior") != "passthrough":
        return {
            "behavior": "passthrough",
            "message": "Command is not read-only, requires further permission checks",
        }
    has_git = any(subcmd.strip().startswith("git ") or subcmd.strip() == "git" for subcmd in split_command_deprecated(command))
    if compoundCommandHasCd and has_git:
        return {
            "behavior": "passthrough",
            "message": "Compound commands with cd and git require permission checks",
        }
    if all(isCommandReadOnly(subcmd) for subcmd in split_command_deprecated(command)):
        return {"behavior": "allow", "updatedInput": input_data}
    return {
        "behavior": "passthrough",
        "message": "Command is not read-only, requires further permission checks",
    }


__all__ = ["checkReadOnlyConstraints", "isCommandSafeViaFlagParsing", "isCommandReadOnly"]
