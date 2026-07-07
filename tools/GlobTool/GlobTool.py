from __future__ import annotations

import fnmatch
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Iterable

from .._runtime import ToolUseContext, expand_path, to_relative_path
from .prompt import DESCRIPTION, GLOB_TOOL_NAME

FILE_NOT_FOUND_CWD_NOTE = "Note: your current working directory is"
DEFAULT_MAX_RESULTS = 100
TOOL_SUMMARY_MAX_LENGTH = 50

# glob是一种文件名匹配原则
"""
1.glob是bash咋执行命令前完成的文件名展开


"""

def _normalize_slashes(value: str) -> str:
    return value.replace("\\", "/")


def _normalize_for_match(value: str) -> str:
    normalized = _normalize_slashes(value)
    return normalized.lower() if os.name == "nt" else normalized


def _match_wildcard_pattern(pattern: str, value: str) -> bool:
    return fnmatch.fnmatchcase(
        _normalize_for_match(value),
        _normalize_for_match(pattern),
    )


def _truncate(value: str, limit: int = TOOL_SUMMARY_MAX_LENGTH) -> str:
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[: limit - 3] + "..."


def _is_env_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


def _suggest_path_under_cwd(path: str, cwd: str) -> str | None:
    cwd_path = Path(cwd).resolve()
    cwd_parent = cwd_path.parent
    target = Path(path)
    try:
        resolved_target = target.parent.resolve() / target.name
    except OSError:
        resolved_target = target
    try:
        resolved_target.relative_to(cwd_parent)
    except ValueError:
        return None
    try:
        resolved_target.relative_to(cwd_path)
        return None
    except ValueError:
        pass
    try:
        relative_to_parent = resolved_target.relative_to(cwd_parent)
    except ValueError:
        return None
    corrected = cwd_path / relative_to_parent
    return str(corrected) if corrected.exists() else None


def _get_permission_context(tool_use_context: ToolUseContext | None) -> dict[str, Any]:
    if tool_use_context is None:
        return {}
    app_state = tool_use_context.getAppState()
    permission_context = getattr(app_state, "tool_permission_context", None)
    if isinstance(permission_context, dict):
        return dict(permission_context)
    if permission_context is not None and hasattr(permission_context, "__dict__"):
        return dict(vars(permission_context))
    config = getattr(app_state, "config", {}) or {}
    fallback = config.get("toolPermissionContext")
    return dict(fallback) if isinstance(fallback, dict) else {}


def _iter_rule_patterns(
    permission_context: dict[str, Any] | None,
    *,
    behavior: str,
) -> Iterable[str]:
    context = dict(permission_context or {})
    candidate_keys = [
        f"{behavior}_read_rules",
        f"{behavior}ReadRules",
        f"read_{behavior}_rules",
        f"read{behavior.title()}Rules",
        f"{behavior}_rules",
        f"{behavior}Rules",
    ]
    seen: set[str] = set()
    for key in candidate_keys:
        rules = context.get(key)
        if not isinstance(rules, list):
            continue
        for rule in rules:
            pattern = str(rule).strip()
            if pattern and pattern not in seen:
                seen.add(pattern)
                yield pattern


def _path_match_candidates(file_path: str, base_dirs: Iterable[str]) -> list[str]:
    absolute_path = os.path.abspath(file_path)
    absolute_posix = _normalize_slashes(absolute_path)
    candidates = {
        absolute_path,
        absolute_posix,
        os.path.basename(absolute_path),
    }

    if os.name == "nt" and len(absolute_path) >= 2 and absolute_path[1] == ":":
        drive = absolute_path[0].lower()
        rest = absolute_posix[2:].lstrip("/")
        candidates.add(f"/{drive}/{rest}")
        candidates.add(f"//{drive}/{rest}")

    for base_dir in base_dirs:
        if not base_dir:
            continue
        base_abs = os.path.abspath(base_dir)
        try:
            relative = os.path.relpath(absolute_path, base_abs)
        except ValueError:
            continue
        if relative.startswith(".."):
            continue
        relative_posix = _normalize_slashes(relative)
        candidates.add(relative_posix)
        candidates.add("/" + relative_posix)
        candidates.add("./" + relative_posix)

    return [candidate for candidate in candidates if candidate]


def _rule_matches_path(
    pattern: str,
    file_path: str,
    *,
    cwd: str,
    permission_context: dict[str, Any] | None,
) -> bool:
    normalized_pattern = pattern
    alternative_patterns = {normalized_pattern}
    if pattern.startswith("~/"):
        alternative_patterns.add(_normalize_slashes(str(Path(pattern).expanduser())))
    if os.name == "nt" and pattern.startswith("//") and len(pattern) >= 4:
        drive_letter = pattern[2]
        if drive_letter.isalpha() and pattern[3] == "/":
            alternative_patterns.add(f"{drive_letter.upper()}:{pattern[3:]}")
    if normalized_pattern.endswith("/**"):
        alternative_patterns.add(normalized_pattern[:-3])

    base_dirs = _get_allowed_working_directories(permission_context, cwd)
    candidates = _path_match_candidates(file_path, base_dirs)
    for candidate in candidates:
        for candidate_pattern in alternative_patterns:
            if _match_wildcard_pattern(candidate_pattern, candidate):
                return True
    return False


def _matching_rule_for_read_input(
    file_path: str,
    permission_context: dict[str, Any] | None,
    *,
    behavior: str,
    cwd: str,
) -> str | None:
    for pattern in _iter_rule_patterns(permission_context, behavior=behavior):
        if _rule_matches_path(
            pattern,
            file_path,
            cwd=cwd,
            permission_context=permission_context,
        ):
            return pattern
    return None


def _get_allowed_working_directories(
    permission_context: dict[str, Any] | None,
    cwd: str,
) -> list[str]:
    context = dict(permission_context or {})
    candidates: list[str] = [cwd]

    allowed_directories = context.get("allowed_directories") or context.get(
        "working_directories"
    )
    if isinstance(allowed_directories, (list, tuple, set)):
        candidates.extend(str(path) for path in allowed_directories if path)

    additional = context.get("additionalWorkingDirectories")
    if isinstance(additional, dict):
        candidates.extend(str(path) for path in additional.keys() if path)
    elif isinstance(additional, (list, tuple, set)):
        candidates.extend(str(path) for path in additional if path)

    additional_snake = context.get("additional_working_directories")
    if isinstance(additional_snake, dict):
        candidates.extend(str(path) for path in additional_snake.keys() if path)
    elif isinstance(additional_snake, (list, tuple, set)):
        candidates.extend(str(path) for path in additional_snake if path)

    resolved: list[str] = []
    seen: set[str] = set()
    for path in candidates:
        normalized = os.path.normcase(os.path.normpath(expand_path(path, cwd)))
        if normalized not in seen:
            seen.add(normalized)
            resolved.append(os.path.normpath(expand_path(path, cwd)))
    return resolved


def _path_in_working_path(path: str, working_path: str) -> bool:
    absolute_path = os.path.normcase(os.path.normpath(expand_path(path)))
    absolute_working_path = os.path.normcase(os.path.normpath(expand_path(working_path)))
    if absolute_path == absolute_working_path:
        return True
    prefix = absolute_working_path
    if not prefix.endswith(os.sep):
        prefix += os.sep
    return absolute_path.startswith(prefix)


def _path_in_allowed_working_path(
    path: str,
    permission_context: dict[str, Any] | None,
    cwd: str,
) -> bool:
    working_dirs = _get_allowed_working_directories(permission_context, cwd)
    return any(_path_in_working_path(path, working_dir) for working_dir in working_dirs)


def _extract_glob_base_directory(pattern: str) -> tuple[str, str]:
    match = re.search(r"[*?[{]", pattern)
    if match is None:
        return os.path.dirname(pattern), os.path.basename(pattern)

    static_prefix = pattern[: match.start()]
    last_sep_index = max(static_prefix.rfind("/"), static_prefix.rfind(os.sep))
    if last_sep_index == -1:
        return "", pattern

    base_dir = static_prefix[:last_sep_index]
    relative_pattern = pattern[last_sep_index + 1 :]

    if base_dir == "" and last_sep_index == 0:
        base_dir = os.sep
    if os.name == "nt" and re.fullmatch(r"[A-Za-z]:", base_dir):
        base_dir += os.sep

    return base_dir, relative_pattern


def _run_ripgrep_glob(
    pattern: str,
    search_dir: str,
    *,
    hidden: bool,
    no_ignore: bool,
) -> list[str] | None:
    ripgrep = shutil.which("rg") or shutil.which("ripgrep")
    if not ripgrep:
        return None

    args = [
        ripgrep,
        "--files",
        "--glob",
        pattern,
        "--sort=modified",
    ]
    if no_ignore:
        args.append("--no-ignore")
    if hidden:
        args.append("--hidden")

    completed = subprocess.run(
        args,
        cwd=search_dir,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if completed.returncode not in (0, 1):
        raise RuntimeError(completed.stderr.strip() or "ripgrep glob search failed")

    paths: list[str] = []
    for line in completed.stdout.splitlines():
        normalized = line.strip()
        if not normalized:
            continue
        if os.path.isabs(normalized):
            paths.append(os.path.normpath(normalized))
        else:
            paths.append(os.path.normpath(os.path.join(search_dir, normalized)))
    return paths


def _path_matches_glob(file_path: Path, pattern: str, search_dir: str) -> bool:
    relative = _normalize_slashes(os.path.relpath(file_path, search_dir))
    normalized_pattern = _normalize_slashes(pattern)
    return fnmatch.fnmatch(file_path.name, normalized_pattern) or fnmatch.fnmatch(
        relative,
        normalized_pattern,
    )


def _walk_glob_matches(
    pattern: str,
    search_dir: str,
    *,
    hidden: bool,
    abort_controller: Any = None,
) -> list[str]:
    base_path = Path(search_dir)
    if base_path.is_file():
        return [str(base_path)] if _path_matches_glob(base_path, pattern, str(base_path.parent)) else []

    results: list[str] = []
    for root, dirs, filenames in os.walk(search_dir):
        if abort_controller is not None and getattr(abort_controller, "aborted", False):
            break
        if not hidden:
            dirs[:] = [name for name in dirs if not name.startswith(".")]
            filenames = [name for name in filenames if not name.startswith(".")]
        root_path = Path(root)
        for filename in filenames:
            file_path = root_path / filename
            if _path_matches_glob(file_path, pattern, search_dir):
                results.append(str(file_path))
    results.sort(key=lambda item: os.path.getmtime(item))
    return results

# 根据glob匹配模式查找文件
def _glob_files(
    file_pattern: str,
    cwd: str,
    *,
    limit: int,  # 返回文件限制
    offset: int, # 从第几个开始返回
    permission_context: dict[str, Any] | None,  # 判断哪些路径允许读取和禁止读取
    abort_controller: Any = None,
) -> tuple[list[str], bool]:
    search_dir = cwd
    search_pattern = file_pattern

    if os.path.isabs(file_pattern):
        base_dir, relative_pattern = _extract_glob_base_directory(file_pattern)
        if base_dir:
            search_dir = base_dir
            search_pattern = relative_pattern

    no_ignore = _is_env_truthy(os.environ.get("CLAUDE_CODE_GLOB_NO_IGNORE", "true"))
    hidden = _is_env_truthy(os.environ.get("CLAUDE_CODE_GLOB_HIDDEN", "true"))

    all_paths = _run_ripgrep_glob(
        search_pattern,
        search_dir,
        hidden=hidden,
        no_ignore=no_ignore,
    )
    if all_paths is None:
        all_paths = _walk_glob_matches(
            search_pattern,
            search_dir,
            hidden=hidden,
            abort_controller=abort_controller,
        )

    filtered_paths = [
        os.path.normpath(path)
        for path in all_paths
        if _matching_rule_for_read_input(
            os.path.normpath(path),
            permission_context,
            behavior="deny",
            cwd=cwd,
        )
        is None
    ]

    truncated = len(filtered_paths) > offset + limit
    return filtered_paths[offset : offset + limit], truncated


class PythonGlobTool:
    name = GLOB_TOOL_NAME
    search_hint = "find files by name pattern or wildcard"
    max_result_size_chars = 100_000
    strict = True
    input_schema = {
        # 文件匹配模式
        "pattern": "The glob pattern to match files against",
        "path": (
            "The directory to search in. If omitted, the current working directory "
            "will be used."
        ),
    }
    output_schema = {
        #  耗时
        "durationMs": "Time taken to execute the search in milliseconds",
        # 匹配文件数
        "numFiles": "Total number of files found",
        # 匹配文件名
        "filenames": "Array of file paths that match the pattern",
        # 是否被截断
        "truncated": "Whether results were truncated",
    }

    async def description(self, _input_data: dict[str, Any] | None = None) -> str:
        return DESCRIPTION

    async def prompt(self) -> str:
        return DESCRIPTION

    def userFacingName(self, _input_data: dict[str, Any] | None = None) -> str:
        return "Search"

    def getToolUseSummary(self, input_data: dict[str, Any] | None) -> str | None:
        pattern = str((input_data or {}).get("pattern", "")).strip()
        return _truncate(pattern) if pattern else None

    def getActivityDescription(self, input_data: dict[str, Any] | None) -> str:
        summary = self.getToolUseSummary(input_data)
        return f"Finding {summary}" if summary else "Finding files"

    def isConcurrencySafe(self, _input_data: dict[str, Any] | None = None) -> bool:
        return True

    def isReadOnly(self, _input_data: dict[str, Any] | None = None) -> bool:
        return True

    def toAutoClassifierInput(self, input_data: dict[str, Any]) -> str:
        return str(input_data.get("pattern", ""))

    def isSearchOrReadCommand(self) -> dict[str, bool]:
        return {"isSearch": True, "isRead": False}

    def getPath(
        self,
        input_data: dict[str, Any],
        context: ToolUseContext | None = None,
    ) -> str:
        cwd = context.options.cwd if context is not None else os.getcwd()
        path = input_data.get("path")
        if isinstance(path, str) and path.strip():
            return expand_path(path, cwd)
        return cwd

    def backfillObservableInput(self, input_data: dict[str, Any]) -> None:
        path = input_data.get("path")
        if isinstance(path, str) and path.strip():
            input_data["path"] = expand_path(path)

    async def preparePermissionMatcher(self, payload: dict[str, Any]):
        pattern = str(payload.get("pattern", ""))

        def _matcher(rule_pattern: str) -> bool:
            return _match_wildcard_pattern(rule_pattern, pattern)

        return _matcher

    async def validateInput(
        self,
        input_data: dict[str, Any],
        toolUseContext: ToolUseContext | None = None,
    ) -> dict[str, Any]:
        pattern = str(input_data.get("pattern", "")).strip()
        if not pattern:
            return {
                "result": False,
                "message": "pattern is required.",
                "errorCode": 1,
            }

        path = input_data.get("path")
        if isinstance(path, str) and path.strip():
            cwd = (
                toolUseContext.options.cwd
                if toolUseContext is not None
                else os.getcwd()
            )
            absolute_path = expand_path(path, cwd)
            if absolute_path.startswith("\\\\") or absolute_path.startswith("//"):
                return {"result": True}
            target = Path(absolute_path)
            if not target.exists():
                suggestion = _suggest_path_under_cwd(absolute_path, cwd)
                message = (
                    f"Directory does not exist: {path}. "
                    f"{FILE_NOT_FOUND_CWD_NOTE} {cwd}."
                )
                if suggestion:
                    message += f" Did you mean {suggestion}?"
                return {
                    "result": False,
                    "message": message,
                    "errorCode": 2,
                }
            if not target.is_dir():
                return {
                    "result": False,
                    "message": f"Path is not a directory: {path}",
                    "errorCode": 3,
                }

        return {"result": True}

    async def checkPermissions(
        self,
        input_data: dict[str, Any],
        context: ToolUseContext | None = None,
    ) -> dict[str, Any]:
        tool_context = context or ToolUseContext()
        permission_context = _get_permission_context(tool_context)
        path = self.getPath(input_data, tool_context)

        if path.startswith("\\\\") or path.startswith("//"):
            return {
                "behavior": "ask",
                "message": (
                    f"Claude requested permissions to read from {path}, which appears "
                    "to be a UNC path that could access network resources."
                ),
                "decisionReason": {
                    "type": "other",
                    "reason": "UNC path detected",
                },
            }

        deny_rule = _matching_rule_for_read_input(
            path,
            permission_context,
            behavior="deny",
            cwd=tool_context.options.cwd,
        )
        if deny_rule is not None:
            return {
                "behavior": "deny",
                "message": f"Permission to read {path} has been denied.",
                "decisionReason": {
                    "type": "rule",
                    "rule": deny_rule,
                    "behavior": "deny",
                },
            }

        ask_rule = _matching_rule_for_read_input(
            path,
            permission_context,
            behavior="ask",
            cwd=tool_context.options.cwd,
        )
        if ask_rule is not None:
            return {
                "behavior": "ask",
                "message": (
                    f"Claude requested permissions to read from {path}, but you "
                    "haven't granted it yet."
                ),
                "decisionReason": {
                    "type": "rule",
                    "rule": ask_rule,
                    "behavior": "ask",
                },
            }

        if _path_in_allowed_working_path(
            path,
            permission_context,
            tool_context.options.cwd,
        ):
            return {
                "behavior": "allow",
                "updatedInput": input_data,
                "decisionReason": {
                    "type": "mode",
                    "mode": str(permission_context.get("mode", "default")),
                },
            }

        allow_rule = _matching_rule_for_read_input(
            path,
            permission_context,
            behavior="allow",
            cwd=tool_context.options.cwd,
        )
        if allow_rule is not None:
            return {
                "behavior": "allow",
                "updatedInput": input_data,
                "decisionReason": {
                    "type": "rule",
                    "rule": allow_rule,
                    "behavior": "allow",
                },
            }

        return {
            "behavior": "ask",
            "message": (
                f"Claude requested permissions to read from {path}, but you "
                "haven't granted it yet."
            ),
            "decisionReason": {
                "type": "workingDir",
                "reason": "Path is outside allowed working directories",
            },
        }

    def extractSearchText(self, output: dict[str, Any]) -> str:
        filenames = output.get("filenames")
        if not isinstance(filenames, list):
            return ""
        return "\n".join(str(item) for item in filenames)

    async def call(
        self,
        *args: Any,
        toolUseContext: ToolUseContext | None = None,
        abortController: Any = None,
        getAppState: Any = None,
        globLimits: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del getAppState
        payload = dict(args[0]) if args and isinstance(args[0], dict) else {}
        payload.update(kwargs)
        context = toolUseContext or ToolUseContext()

        validation = await self.validateInput(payload, context)
        if not validation.get("result"):
            raise ValueError(str(validation.get("message", "Invalid glob request.")))

        start = time.perf_counter()
        limit = DEFAULT_MAX_RESULTS
        if isinstance(globLimits, dict):
            try:
                limit = max(int(globLimits.get("maxResults", limit)), 1)
            except (TypeError, ValueError):
                limit = DEFAULT_MAX_RESULTS

        search_root = self.getPath(payload, context)
        files, truncated = _glob_files(
            str(payload.get("pattern", "")),
            search_root,
            limit=limit,
            offset=0,
            permission_context=_get_permission_context(context),
            abort_controller=abortController or context.abort_controller,
        )
        filenames = [
            to_relative_path(path, context.options.cwd)
            for path in files
        ]
        output = {
            "filenames": filenames,
            "durationMs": int((time.perf_counter() - start) * 1000),
            "numFiles": len(filenames),
            "truncated": truncated,
        }
        return {"data": output}

    def mapToolResultToToolResultBlockParam(
        self,
        output: dict[str, Any],
        tool_use_id: str,
    ) -> dict[str, Any]:
        filenames = output.get("filenames")
        if not isinstance(filenames, list) or not filenames:
            return {
                "tool_use_id": tool_use_id,
                "type": "tool_result",
                "content": "No files found",
            }

        lines = [str(item) for item in filenames]
        if output.get("truncated"):
            lines.append(
                "(Results are truncated. Consider using a more specific path or pattern.)"
            )
        return {
            "tool_use_id": tool_use_id,
            "type": "tool_result",
            "content": "\n".join(lines),
        }


GlobTool = PythonGlobTool()

__all__ = [
    "DEFAULT_MAX_RESULTS",
    "FILE_NOT_FOUND_CWD_NOTE",
    "GlobTool",
    "PythonGlobTool",
]
