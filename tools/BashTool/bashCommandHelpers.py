from __future__ import annotations

import os
import re
import shlex
from typing import Any, Callable


SAFE_ENV_VARS = {
    "GOEXPERIMENT",
    "GOOS",
    "GOARCH",
    "CGO_ENABLED",
    "GO111MODULE",
    "RUST_BACKTRACE",
    "RUST_LOG",
    "NODE_ENV",
    "PYTHONUNBUFFERED",
    "PYTHONDONTWRITEBYTECODE",
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
    "PYTEST_DEBUG",
    "ANTHROPIC_API_KEY",
    "LANG",
    "LANGUAGE",
    "LC_ALL",
    "LC_CTYPE",
    "LC_TIME",
    "CHARSET",
    "TERM",
    "COLORTERM",
    "NO_COLOR",
    "FORCE_COLOR",
    "TZ",
    "LS_COLORS",
    "LSCOLORS",
    "GREP_COLOR",
    "GREP_COLORS",
    "GCC_COLORS",
    "TIME_STYLE",
    "BLOCK_SIZE",
    "BLOCKSIZE",
}

SAFE_WRAPPERS = {"time", "nohup", "timeout", "nice", "stdbuf", "env"}
ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _shell_tokenize(command: str) -> list[str]:
    return shlex.split(command, posix=True)


def split_command_with_operators(command: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    escaped = False
    i = 0
    while i < len(command):
        char = command[i]
        if escaped:
            current.append(char)
            escaped = False
            i += 1
            continue
        if char == "\\" and not in_single:
            current.append(char)
            escaped = True
            i += 1
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            current.append(char)
            i += 1
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            current.append(char)
            i += 1
            continue
        if not in_single and not in_double:
            operator = None
            for candidate in ("&&", "||", ">>", ">&"):
                if command.startswith(candidate, i):
                    operator = candidate
                    break
            if operator is None and char in {"|", ";", ">"}:
                operator = char
            if operator is not None:
                chunk = "".join(current).strip()
                if chunk:
                    parts.append(chunk)
                parts.append(operator)
                current = []
                i += len(operator)
                continue
        current.append(char)
        i += 1
    chunk = "".join(current).strip()
    if chunk:
        parts.append(chunk)
    return parts


def split_command_deprecated(command: str) -> list[str]:
    parts = split_command_with_operators(command)
    segments: list[str] = []
    current: list[str] = []
    skip_redirect_target = False
    for part in parts:
        if skip_redirect_target:
            skip_redirect_target = False
            continue
        if part in {">", ">>", ">&"}:
            skip_redirect_target = True
            continue
        if part in {"&&", "||", "|", ";"}:
            joined = " ".join(piece for piece in current if piece).strip()
            if joined:
                segments.append(joined)
            current = []
            continue
        current.append(part)
    joined = " ".join(piece for piece in current if piece).strip()
    if joined:
        segments.append(joined)
    return segments


def extract_output_redirections(command: str) -> dict[str, Any]:
    parts = split_command_with_operators(command)
    redirections: list[dict[str, str]] = []
    dangerous = False
    i = 0
    while i < len(parts):
        part = parts[i]
        if part in {">", ">>", ">&"}:
            target = parts[i + 1] if i + 1 < len(parts) else ""
            if "$" in target or "%" in target:
                dangerous = True
            if target:
                redirections.append({"target": target, "operator": ">>" if part == ">>" else ">"})
            i += 2
            continue
        i += 1
    return {"redirections": redirections, "hasDangerousRedirection": dangerous}


def strip_all_leading_env_vars(command: str, safe_env_vars: set[str] | None = None) -> str:
    safe_env_vars = SAFE_ENV_VARS if safe_env_vars is None else safe_env_vars
    try:
        tokens = _shell_tokenize(command)
    except ValueError:
        return command.strip()
    index = 0
    while index < len(tokens) and ENV_ASSIGNMENT_RE.match(tokens[index]):
        var_name = tokens[index].split("=", 1)[0]
        if var_name not in safe_env_vars:
            break
        index += 1
    return " ".join(tokens[index:]) if index < len(tokens) else ""


def _skip_timeout(tokens: list[str], index: int) -> int:
    i = index + 1
    while i < len(tokens) and tokens[i].startswith("-"):
        flag = tokens[i]
        if flag in {"-k", "-s", "--kill-after", "--signal"} and i + 1 < len(tokens):
            i += 2
        elif flag in {"-v", "--foreground", "--preserve-status", "--verbose"}:
            i += 1
        elif re.match(r"^--(?:kill-after|signal)=.+$", flag):
            i += 1
        else:
            break
    if i < len(tokens):
        i += 1
    return i


def _skip_nice(tokens: list[str], index: int) -> int:
    i = index + 1
    if i < len(tokens) and tokens[i] == "-n" and i + 1 < len(tokens):
        return i + 2
    if i < len(tokens) and re.match(r"^-\d+$", tokens[i]):
        return i + 1
    return i


def _skip_stdbuf(tokens: list[str], index: int) -> int:
    i = index + 1
    consumed = False
    while i < len(tokens):
        flag = tokens[i]
        if re.match(r"^-[ioe]$", flag) and i + 1 < len(tokens):
            i += 2
            consumed = True
        elif re.match(r"^-[ioe].+", flag) or re.match(r"^--(input|output|error)=.+$", flag):
            i += 1
            consumed = True
        else:
            break
    return i if consumed else index


def _skip_env_wrapper(tokens: list[str], index: int) -> int:
    i = index + 1
    while i < len(tokens):
        token = tokens[i]
        if ENV_ASSIGNMENT_RE.match(token):
            i += 1
        elif token in {"-i", "-0", "-v"}:
            i += 1
        elif token == "-u" and i + 1 < len(tokens):
            i += 2
        else:
            break
    return i


def strip_safe_wrappers(command: str) -> str:
    stripped = strip_all_leading_env_vars(command)
    try:
        tokens = _shell_tokenize(stripped)
    except ValueError:
        return stripped
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "time" or token == "nohup":
            index += 1
        elif token == "timeout":
            index = _skip_timeout(tokens, index)
        elif token == "nice":
            index = _skip_nice(tokens, index)
        elif token == "stdbuf":
            new_index = _skip_stdbuf(tokens, index)
            if new_index == index:
                break
            index = new_index
        elif token == "env":
            index = _skip_env_wrapper(tokens, index)
        else:
            break
    return " ".join(tokens[index:]) if index < len(tokens) else ""


def strip_wrappers_from_argv(argv: list[str]) -> list[str]:
    joined = " ".join(argv)
    try:
        return _shell_tokenize(strip_safe_wrappers(joined))
    except ValueError:
        return list(argv)


async def checkCommandOperatorPermissions(
    input_data: dict[str, Any],
    bashToolHasPermissionFn: Callable[[dict[str, Any]], Any],
    checkers: dict[str, Callable[[str], bool]],
    astRoot: Any = None,
) -> dict[str, Any]:
    del astRoot
    command = str(input_data.get("command", ""))
    if "$(" in command or "`" in command:
        return {
            "behavior": "ask",
            "message": "Command substitution requires explicit approval.",
            "decisionReason": {"type": "other", "reason": "Command substitution requires approval"},
        }
    segments = [segment for segment in command.split("|") if segment.strip()]
    if len(segments) <= 1:
        return {"behavior": "passthrough", "message": "No pipe operators found"}
    has_cd = any(checkers["isNormalizedCdCommand"](segment.strip()) for segment in segments)
    has_git = any(checkers["isNormalizedGitCommand"](segment.strip()) for segment in segments)
    if has_cd and has_git:
        return {
            "behavior": "ask",
            "message": "Compound commands with cd and git require approval.",
            "decisionReason": {"type": "other", "reason": "Compound cd+git command"},
        }
    results = []
    for segment in segments:
        result = bashToolHasPermissionFn({**input_data, "command": segment.strip()})
        if hasattr(result, "__await__"):
            result = await result
        results.append(result)
    if all(result.get("behavior") == "allow" for result in results):
        return {"behavior": "allow", "updatedInput": input_data}
    return {
        "behavior": "ask",
        "message": "Piped command requires approval.",
        "decisionReason": {"type": "other", "reason": "Piped command contains non-allow segment"},
        "subcommandResults": results,
    }


__all__ = [
    "ENV_ASSIGNMENT_RE",
    "SAFE_ENV_VARS",
    "SAFE_WRAPPERS",
    "checkCommandOperatorPermissions",
    "extract_output_redirections",
    "split_command_deprecated",
    "split_command_with_operators",
    "strip_all_leading_env_vars",
    "strip_safe_wrappers",
    "strip_wrappers_from_argv",
]
