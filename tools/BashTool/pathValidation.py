from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Any, Callable

from .bashCommandHelpers import (
    extract_output_redirections,
    split_command_deprecated,
    strip_safe_wrappers,
    strip_wrappers_from_argv,
)
from .sedValidation import sedCommandIsAllowedByAllowlist

PathCommand = str


def _extract_non_flag_args(args: list[str]) -> list[str]:
    result: list[str] = []
    after_double_dash = False
    for arg in args:
        if after_double_dash:
            result.append(arg)
        elif arg == "--":
            after_double_dash = True
        elif not arg.startswith("-"):
            result.append(arg)
    return result


def _parse_pattern_command(args: list[str], flags_with_args: set[str], defaults: list[str] | None = None) -> list[str]:
    defaults = defaults or []
    paths: list[str] = []
    pattern_found = False
    after_double_dash = False
    i = 0
    while i < len(args):
        arg = args[i]
        if not after_double_dash and arg == "--":
            after_double_dash = True
            i += 1
            continue
        if not after_double_dash and arg.startswith("-"):
            flag = arg.split("=", 1)[0]
            if flag in {"-e", "--regexp", "-f", "--file"}:
                pattern_found = True
            if flag in flags_with_args and "=" not in arg and i + 1 < len(args):
                i += 2
                continue
            i += 1
            continue
        if not pattern_found:
            pattern_found = True
        else:
            paths.append(arg)
        i += 1
    return paths if paths else list(defaults)


def _extract_find_paths(args: list[str]) -> list[str]:
    paths: list[str] = []
    found_non_global_flag = False
    after_double_dash = False
    for arg in args:
        if after_double_dash:
            paths.append(arg)
            continue
        if arg == "--":
            after_double_dash = True
            continue
        if arg.startswith("-"):
            if arg in {"-H", "-L", "-P"}:
                continue
            found_non_global_flag = True
            continue
        if not found_non_global_flag:
            paths.append(arg)
    return paths or ["."]


def _extract_sed_paths(args: list[str]) -> list[str]:
    paths: list[str] = []
    script_found = False
    after_double_dash = False
    i = 0
    while i < len(args):
        arg = args[i]
        if not after_double_dash and arg == "--":
            after_double_dash = True
            i += 1
            continue
        if not after_double_dash and arg.startswith("-"):
            if arg in {"-f", "--file"} and i + 1 < len(args):
                paths.append(args[i + 1])
                script_found = True
                i += 2
                continue
            if arg in {"-e", "--expression"}:
                script_found = True
                i += 2
                continue
            if "e" in arg or "f" in arg:
                script_found = True
            i += 1
            continue
        if not script_found:
            script_found = True
        else:
            paths.append(arg)
        i += 1
    return paths


def _extract_jq_paths(args: list[str]) -> list[str]:
    flags_with_args = {
        "-e",
        "--expression",
        "-f",
        "--from-file",
        "--arg",
        "--argjson",
        "--slurpfile",
        "--rawfile",
        "--args",
        "--jsonargs",
        "-L",
        "--library-path",
        "--indent",
        "--tab",
    }
    paths: list[str] = []
    filter_found = False
    after_double_dash = False
    i = 0
    while i < len(args):
        arg = args[i]
        if not after_double_dash and arg == "--":
            after_double_dash = True
            i += 1
            continue
        if not after_double_dash and arg.startswith("-"):
            flag = arg.split("=", 1)[0]
            if flag in {"-e", "--expression"}:
                filter_found = True
            if flag in flags_with_args and "=" not in arg and i + 1 < len(args):
                i += 2
                continue
            i += 1
            continue
        if not filter_found:
            filter_found = True
        else:
            paths.append(arg)
        i += 1
    return paths


PATH_EXTRACTORS: dict[PathCommand, Callable[[list[str]], list[str]]] = {
    "cd": lambda args: [os.path.expanduser(args[0])] if args else [str(Path.home())],
    "ls": lambda args: _extract_non_flag_args(args) or ["."],
    "find": _extract_find_paths,
    "mkdir": _extract_non_flag_args,
    "touch": _extract_non_flag_args,
    "rm": _extract_non_flag_args,
    "rmdir": _extract_non_flag_args,
    "mv": _extract_non_flag_args,
    "cp": _extract_non_flag_args,
    "cat": _extract_non_flag_args,
    "head": _extract_non_flag_args,
    "tail": _extract_non_flag_args,
    "sort": _extract_non_flag_args,
    "uniq": _extract_non_flag_args,
    "wc": _extract_non_flag_args,
    "cut": _extract_non_flag_args,
    "paste": _extract_non_flag_args,
    "column": _extract_non_flag_args,
    "tr": _extract_non_flag_args,
    "file": _extract_non_flag_args,
    "stat": _extract_non_flag_args,
    "diff": _extract_non_flag_args,
    "awk": _extract_non_flag_args,
    "strings": _extract_non_flag_args,
    "hexdump": _extract_non_flag_args,
    "od": _extract_non_flag_args,
    "base64": _extract_non_flag_args,
    "nl": _extract_non_flag_args,
    "grep": lambda args: _parse_pattern_command(
        args,
        {
            "-e",
            "--regexp",
            "-f",
            "--file",
            "--exclude",
            "--include",
            "--exclude-dir",
            "--include-dir",
            "-m",
            "--max-count",
            "-A",
            "--after-context",
            "-B",
            "--before-context",
            "-C",
            "--context",
        },
    ),
    "rg": lambda args: _parse_pattern_command(
        args,
        {
            "-e",
            "--regexp",
            "-f",
            "--file",
            "-t",
            "--type",
            "-T",
            "--type-not",
            "-g",
            "--glob",
            "-m",
            "--max-count",
            "--max-depth",
            "-r",
            "--replace",
            "-A",
            "--after-context",
            "-B",
            "--before-context",
            "-C",
            "--context",
        },
        ["."],
    ),
    "sed": _extract_sed_paths,
    "git": lambda _args: [],
    "jq": _extract_jq_paths,
    "sha256sum": _extract_non_flag_args,
    "sha1sum": _extract_non_flag_args,
    "md5sum": _extract_non_flag_args,
}

COMMAND_OPERATION_TYPE: dict[PathCommand, str] = {
    "cd": "read",
    "ls": "read",
    "find": "read",
    "mkdir": "create",
    "touch": "create",
    "rm": "write",
    "rmdir": "write",
    "mv": "write",
    "cp": "write",
    "cat": "read",
    "head": "read",
    "tail": "read",
    "sort": "read",
    "uniq": "read",
    "wc": "read",
    "cut": "read",
    "paste": "read",
    "column": "read",
    "tr": "read",
    "file": "read",
    "stat": "read",
    "diff": "read",
    "awk": "read",
    "strings": "read",
    "hexdump": "read",
    "od": "read",
    "base64": "read",
    "nl": "read",
    "grep": "read",
    "rg": "read",
    "sed": "write",
    "git": "read",
    "jq": "read",
    "sha256sum": "read",
    "sha1sum": "read",
    "md5sum": "read",
}


def _normalize_permission_context(
    toolPermissionContext: dict[str, Any] | None,
    cwd: str,
) -> dict[str, Any]:
    context = dict(toolPermissionContext or {})
    allowed = context.get("allowed_directories") or context.get("working_directories") or [cwd]
    context["allowed_directories"] = [str(Path(path).expanduser().resolve()) for path in allowed]
    return context


def _resolve_path(path: str, cwd: str) -> str:
    expanded = os.path.expanduser(path.strip('"').strip("'"))
    return str(Path(expanded if os.path.isabs(expanded) else os.path.join(cwd, expanded)).resolve())


def _is_within_allowed(path: str, allowed_directories: list[str]) -> bool:
    target = Path(path)
    for allowed in allowed_directories:
        allowed_path = Path(allowed)
        try:
            target.relative_to(allowed_path)
            return True
        except ValueError:
            continue
    return False


def _is_dangerous_removal_path(path: str) -> bool:
    target = Path(path)
    dangerous = {
        Path("/"),
        Path.home(),
        Path.home().parent,
    }
    if os.name == "nt":
        for drive in ("C:\\", "D:\\", "E:\\"):
            dangerous.add(Path(drive))
    return target in dangerous


def _build_path_message(resolved_path: str, operation: str, allowed_directories: list[str]) -> str:
    return (
        f"{operation.capitalize()} access to '{resolved_path}' is outside the allowed working "
        f"directories for this session: {', '.join(allowed_directories)}"
    )


def createPathChecker(command: PathCommand, operationTypeOverride: str | None = None):
    operation_type = operationTypeOverride or COMMAND_OPERATION_TYPE[command]

    def _checker(
        args: list[str],
        cwd: str,
        toolPermissionContext: dict[str, Any] | None,
        compoundCommandHasCd: bool = False,
    ) -> dict[str, Any]:
        context = _normalize_permission_context(toolPermissionContext, cwd)
        allowed_directories = context["allowed_directories"]
        if compoundCommandHasCd and operation_type != "read":
            return {
                "behavior": "ask",
                "message": "Commands that change directories and then write require approval.",
                "decisionReason": {
                    "type": "other",
                    "reason": "Compound command contains cd before a write operation",
                },
            }
        paths = PATH_EXTRACTORS[command](args)
        for raw_path in paths:
            resolved_path = _resolve_path(raw_path, cwd)
            if command in {"rm", "rmdir"} and _is_dangerous_removal_path(resolved_path):
                return {
                    "behavior": "ask",
                    "message": f"Dangerous {command} operation detected: {resolved_path}",
                    "decisionReason": {
                        "type": "other",
                        "reason": f"Dangerous removal path: {resolved_path}",
                    },
                    "suggestions": [],
                }
            if not _is_within_allowed(resolved_path, allowed_directories):
                return {
                    "behavior": "ask",
                    "message": _build_path_message(resolved_path, operation_type, allowed_directories),
                    "blockedPath": resolved_path,
                    "decisionReason": {
                        "type": "path",
                        "path": resolved_path,
                        "operation": operation_type,
                    },
                    "suggestions": [
                        {
                            "type": "addDirectories",
                            "directories": [str(Path(resolved_path).parent)],
                            "destination": "session",
                        }
                    ],
                }
        return {"behavior": "passthrough", "message": "All paths are within allowed directories"}

    return _checker


def _parse_command_arguments(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return []


def _validate_single_path_command(
    command: str,
    cwd: str,
    toolPermissionContext: dict[str, Any] | None,
    compoundCommandHasCd: bool,
) -> dict[str, Any]:
    stripped = strip_safe_wrappers(command)
    argv = _parse_command_arguments(stripped)
    if not argv:
        return {"behavior": "passthrough", "message": "Unable to parse command arguments"}
    base_cmd, *args = argv
    if base_cmd not in PATH_EXTRACTORS:
        return {"behavior": "passthrough", "message": f"{base_cmd} is not a path-restricted command"}
    operation_override = "read" if base_cmd == "sed" and sedCommandIsAllowedByAllowlist(stripped) else None
    return createPathChecker(base_cmd, operation_override)(args, cwd, toolPermissionContext, compoundCommandHasCd)


def _validate_output_redirections(
    command: str,
    cwd: str,
    toolPermissionContext: dict[str, Any] | None,
    compoundCommandHasCd: bool,
) -> dict[str, Any]:
    context = _normalize_permission_context(toolPermissionContext, cwd)
    extracted = extract_output_redirections(command)
    if extracted["hasDangerousRedirection"]:
        return {
            "behavior": "ask",
            "message": "Shell expansion syntax in redirection paths requires manual approval.",
            "decisionReason": {
                "type": "other",
                "reason": "Shell expansion syntax in redirection paths",
            },
        }
    if compoundCommandHasCd and extracted["redirections"]:
        return {
            "behavior": "ask",
            "message": "Commands that change directories and redirect output require approval.",
            "decisionReason": {
                "type": "other",
                "reason": "Compound command contains cd with output redirection",
            },
        }
    for redirect in extracted["redirections"]:
        target = redirect["target"]
        if target == "/dev/null":
            continue
        resolved = _resolve_path(target, cwd)
        if not _is_within_allowed(resolved, context["allowed_directories"]):
            return {
                "behavior": "ask",
                "message": _build_path_message(resolved, "create", context["allowed_directories"]),
                "blockedPath": resolved,
                "decisionReason": {
                    "type": "path",
                    "path": resolved,
                    "operation": "create",
                },
                "suggestions": [
                    {
                        "type": "addDirectories",
                        "directories": [str(Path(resolved).parent)],
                        "destination": "session",
                    }
                ],
            }
    return {"behavior": "passthrough", "message": "No unsafe redirections found"}


def checkPathConstraints(
    input_data: dict[str, Any],
    cwd: str,
    toolPermissionContext: dict[str, Any] | None,
    compoundCommandHasCd: bool = False,
    astRedirects: Any = None,
    astCommands: Any = None,
) -> dict[str, Any]:
    del astRedirects, astCommands
    command = str(input_data.get("command", ""))
    if ">(" in command or "<(" in command:
        return {
            "behavior": "ask",
            "message": "Process substitution requires manual approval.",
            "decisionReason": {"type": "other", "reason": "Process substitution requires approval"},
        }
    redirection_result = _validate_output_redirections(
        command,
        cwd,
        toolPermissionContext,
        compoundCommandHasCd,
    )
    if redirection_result.get("behavior") != "passthrough":
        return redirection_result
    for subcommand in split_command_deprecated(command):
        result = _validate_single_path_command(subcommand, cwd, toolPermissionContext, compoundCommandHasCd)
        if result.get("behavior") in {"ask", "deny"}:
            return result
    return {"behavior": "passthrough", "message": "All path commands validated successfully"}


__all__ = [
    "COMMAND_OPERATION_TYPE",
    "PATH_EXTRACTORS",
    "PathCommand",
    "checkPathConstraints",
    "createPathChecker",
    "stripWrappersFromArgv",
]


stripWrappersFromArgv = strip_wrappers_from_argv
