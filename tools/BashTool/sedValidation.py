from __future__ import annotations

import re
import shlex
from typing import Any

from .bashCommandHelpers import split_command_deprecated


def _validateFlagsAgainstAllowlist(flags: list[str], allowedFlags: list[str]) -> bool:
    for flag in flags:
        if flag.startswith("-") and not flag.startswith("--") and len(flag) > 2:
            for char in flag[1:]:
                if f"-{char}" not in allowedFlags:
                    return False
        elif flag not in allowedFlags:
            return False
    return True


def isPrintCommand(cmd: str) -> bool:
    return bool(re.fullmatch(r"(?:\d+|\d+,\d+)?p", cmd.strip()))


def isLinePrintingCommand(command: str, expressions: list[str]) -> bool:
    sed_match = re.match(r"^\s*sed\s+", command)
    if not sed_match:
        return False
    try:
        parsed = shlex.split(command[sed_match.end() :], posix=True)
    except ValueError:
        return False
    flags = [arg for arg in parsed if arg.startswith("-") and arg != "--"]
    allowed_flags = [
        "-n",
        "--quiet",
        "--silent",
        "-E",
        "--regexp-extended",
        "-r",
        "-z",
        "--zero-terminated",
        "--posix",
    ]
    if not _validateFlagsAgainstAllowlist(flags, allowed_flags):
        return False
    has_n_flag = any(flag in {"-n", "--quiet", "--silent"} or "n" in flag[1:] for flag in flags)
    if not has_n_flag or not expressions:
        return False
    for expr in expressions:
        for cmd in expr.split(";"):
            if not isPrintCommand(cmd.strip()):
                return False
    return True


def _isSubstitutionCommand(
    command: str,
    expressions: list[str],
    hasFileArguments: bool,
    *,
    allowFileWrites: bool = False,
) -> bool:
    if not allowFileWrites and hasFileArguments:
        return False
    sed_match = re.match(r"^\s*sed\s+", command)
    if not sed_match:
        return False
    try:
        parsed = shlex.split(command[sed_match.end() :], posix=True)
    except ValueError:
        return False
    flags = [arg for arg in parsed if arg.startswith("-") and arg != "--"]
    allowed_flags = ["-E", "--regexp-extended", "-r", "--posix"]
    if allowFileWrites:
        allowed_flags.extend(["-i", "--in-place"])
    if not _validateFlagsAgainstAllowlist(flags, allowed_flags):
        return False
    if len(expressions) != 1:
        return False
    expr = expressions[0].strip()
    if not expr.startswith("s/"):
        return False
    rest = expr[2:]
    delimiter_count = 0
    last_delimiter_pos = -1
    i = 0
    while i < len(rest):
        if rest[i] == "\\":
            i += 2
            continue
        if rest[i] == "/":
            delimiter_count += 1
            last_delimiter_pos = i
        i += 1
    if delimiter_count != 2:
        return False
    expr_flags = rest[last_delimiter_pos + 1 :]
    return bool(re.fullmatch(r"[gpimIM]*[1-9]?[gpimIM]*", expr_flags))


def hasFileArgs(command: str) -> bool:
    sed_match = re.match(r"^\s*sed\s+", command)
    if not sed_match:
        return False
    try:
        parsed = shlex.split(command[sed_match.end() :], posix=True)
    except ValueError:
        return True
    arg_count = 0
    has_e_flag = False
    i = 0
    while i < len(parsed):
        arg = parsed[i]
        if arg in {"-e", "--expression"} and i + 1 < len(parsed):
            has_e_flag = True
            i += 2
            continue
        if arg.startswith("--expression=") or arg.startswith("-e="):
            has_e_flag = True
            i += 1
            continue
        if arg.startswith("-"):
            i += 1
            continue
        arg_count += 1
        if has_e_flag or arg_count > 1:
            return True
        i += 1
    return False


def extractSedExpressions(command: str) -> list[str]:
    expressions: list[str] = []
    sed_match = re.match(r"^\s*sed\s+", command)
    if not sed_match:
        return expressions
    without_sed = command[sed_match.end() :]
    if re.search(r"-e[wWe]|-w[eE]", without_sed):
        raise ValueError("Dangerous flag combination detected")
    try:
        parsed = shlex.split(without_sed, posix=True)
    except ValueError as exc:
        raise ValueError(f"Malformed shell syntax: {exc}") from exc
    found_e_flag = False
    found_expression = False
    i = 0
    while i < len(parsed):
        arg = parsed[i]
        if arg in {"-e", "--expression"} and i + 1 < len(parsed):
            found_e_flag = True
            expressions.append(parsed[i + 1])
            i += 2
            continue
        if arg.startswith("--expression="):
            found_e_flag = True
            expressions.append(arg.split("=", 1)[1])
            i += 1
            continue
        if arg.startswith("-e="):
            found_e_flag = True
            expressions.append(arg.split("=", 1)[1])
            i += 1
            continue
        if arg.startswith("-"):
            i += 1
            continue
        if not found_e_flag and not found_expression:
            expressions.append(arg)
            found_expression = True
            i += 1
            continue
        break
    return expressions


def _containsDangerousOperations(expression: str) -> bool:
    cmd = expression.strip()
    if not cmd:
        return False
    if re.search(r"[^\x01-\x7F]", cmd):
        return True
    if "{" in cmd or "}" in cmd or "\n" in cmd:
        return True
    hash_index = cmd.find("#")
    if hash_index != -1 and not (hash_index > 0 and cmd[hash_index - 1] == "s"):
        return True
    if re.search(r"^!|[/\d$]!", cmd):
        return True
    if re.search(r"\d\s*~\s*\d|,\s*~\s*\d|\$\s*~\s*\d", cmd):
        return True
    if re.search(r"^,|,\s*[+-]", cmd):
        return True
    if re.search(r"s\\|\\[|#%@]", cmd):
        return True
    if re.search(r"\\\/.*[wW]", cmd):
        return True
    if re.search(r"/[^/]*\s+[wWeE]", cmd):
        return True
    if cmd.startswith("s/") and not re.fullmatch(r"s/[^/]*/[^/]*/[^/]*", cmd):
        return True
    if re.match(r"^s.", cmd) and re.search(r"[wWeE]$", cmd):
        proper_subst = re.fullmatch(r"s([^\\\n]).*?\1.*?\1[^wWeE]*", cmd)
        if proper_subst is None:
            return True
    if re.search(
        r"^[wW]\s*\S+|^\d+\s*[wW]\s*\S+|^\$\s*[wW]\s*\S+|^\d+,\d+\s*[wW]\s*\S+|^\d+,\$\s*[wW]\s*\S+",
        cmd,
    ):
        return True
    if re.search(r"^e|^\d+\s*e|^\$\s*e|^\d+,\d+\s*e|^\d+,\$\s*e", cmd):
        return True
    substitution_match = re.match(r"s([^\\\n]).*?\1.*?\1(.*?)$", cmd)
    if substitution_match:
        flags = substitution_match.group(2) or ""
        if "w" in flags or "W" in flags or "e" in flags or "E" in flags:
            return True
    if re.match(r"y([^\\\n])", cmd) and re.search(r"[wWeE]", cmd):
        return True
    return False


def sedCommandIsAllowedByAllowlist(
    command: str,
    options: dict[str, Any] | None = None,
) -> bool:
    allow_file_writes = bool((options or {}).get("allowFileWrites"))
    try:
        expressions = extractSedExpressions(command)
    except ValueError:
        return False
    has_file_arguments = hasFileArgs(command)
    if allow_file_writes:
        is_pattern2 = _isSubstitutionCommand(
            command,
            expressions,
            has_file_arguments,
            allowFileWrites=True,
        )
        if not is_pattern2:
            return False
    else:
        is_pattern1 = isLinePrintingCommand(command, expressions)
        is_pattern2 = _isSubstitutionCommand(command, expressions, has_file_arguments)
        if not is_pattern1 and not is_pattern2:
            return False
        if is_pattern2 and any(";" in expr for expr in expressions):
            return False
    return not any(_containsDangerousOperations(expr) for expr in expressions)


def checkSedConstraints(
    input_data: dict[str, Any],
    toolPermissionContext: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mode = (toolPermissionContext or {}).get("mode", "default")
    allow_file_writes = mode == "acceptEdits"
    for cmd in split_command_deprecated(str(input_data.get("command", ""))):
        trimmed = cmd.strip()
        base_cmd = trimmed.split(maxsplit=1)[0] if trimmed else ""
        if base_cmd != "sed":
            continue
        if not sedCommandIsAllowedByAllowlist(trimmed, {"allowFileWrites": allow_file_writes}):
            return {
                "behavior": "ask",
                "message": "sed command requires approval (contains potentially dangerous operations)",
                "decisionReason": {
                    "type": "other",
                    "reason": "sed command contains operations that require explicit approval",
                },
            }
    return {"behavior": "passthrough", "message": "No dangerous sed operations detected"}


__all__ = [
    "checkSedConstraints",
    "extractSedExpressions",
    "hasFileArgs",
    "isLinePrintingCommand",
    "isPrintCommand",
    "sedCommandIsAllowedByAllowlist",
]
