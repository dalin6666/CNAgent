from __future__ import annotations

import fnmatch
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable

from .._runtime import ToolUseContext, expand_path, to_relative_path
from ..GlobTool.GlobTool import (
    FILE_NOT_FOUND_CWD_NOTE,
    _get_permission_context,
    _matching_rule_for_read_input,
    _match_wildcard_pattern,
    _path_in_allowed_working_path,
    _suggest_path_under_cwd,
)
from .UI import (
    getToolUseSummary,
    renderToolResultMessage,
    renderToolUseErrorMessage,
    renderToolUseMessage,
)
from .prompt import GREP_TOOL_NAME, getDescription


VCS_DIRECTORIES_TO_EXCLUDE = (
    ".git",
    ".svn",
    ".hg",
    ".bzr",
    ".jj",
    ".sl",
)

DEFAULT_HEAD_LIMIT = 250
DEFAULT_TIMEOUT_SECONDS = 20
_CONTENT_WITH_LINE_RE = re.compile(r"^(.*)([:\-])(\d+)([:\-])(.*)$")

# 文件类型别名表
RIPGREP_TYPE_ALIASES: dict[str, set[str]] = {
    "c": {"c", "h"},
    "cpp": {"cc", "cpp", "cxx", "hh", "hpp", "hxx"},
    "csharp": {"cs"},
    "css": {"css", "less", "sass", "scss"},
    "go": {"go"},
    "html": {"htm", "html"},
    "java": {"java"},
    "js": {"cjs", "js", "jsx", "mjs"},
    "json": {"json"},
    "jsx": {"jsx"},
    "kt": {"kt", "kts"},
    "markdown": {"markdown", "md", "mdx"},
    "md": {"markdown", "md", "mdx"},
    "php": {"php"},
    "py": {"py", "pyi", "pyw"},
    "rb": {"rb"},
    "rs": {"rs"},
    "rust": {"rs"},
    "sh": {"bash", "fish", "sh", "zsh"},
    "shell": {"bash", "fish", "sh", "zsh"},
    "swift": {"swift"},
    "ts": {"cts", "mts", "ts", "tsx"},
    "tsx": {"tsx"},
    "xml": {"xml"},
    "yaml": {"yaml", "yml"},
    "yml": {"yaml", "yml"},
}

# 定义英文单词复数
def _plural(count: int, noun: str) -> str:
    if count == 1:
        return noun
    if noun.endswith(("s", "x", "z", "ch", "sh")):
        return f"{noun}es"
    if noun.endswith("y") and len(noun) > 1 and noun[-2].lower() not in "aeiou":
        return noun[:-1] + "ies"
    return f"{noun}s"


def _normalize_slashes(value: str) -> str:
    return value.replace("\\", "/")


def _apply_head_limit(
    items: list[Any],
    limit: int | None,
    offset: int = 0,
) -> dict[str, Any]:
    effective_offset = max(int(offset or 0), 0)
    if limit == 0:
        return {
            "items": items[effective_offset:],
            "appliedLimit": None,
        }

    effective_limit = DEFAULT_HEAD_LIMIT if limit is None else max(int(limit), 0)
    sliced = items[effective_offset : effective_offset + effective_limit]
    was_truncated = len(items) - effective_offset > effective_limit
    return {
        "items": sliced,
        "appliedLimit": effective_limit if was_truncated else None,
    }


def _format_limit_info(
    applied_limit: int | None,
    applied_offset: int | None,
) -> str:
    parts: list[str] = []
    if applied_limit is not None:
        parts.append(f"limit: {applied_limit}")
    if applied_offset:
        parts.append(f"offset: {applied_offset}")
    return ", ".join(parts)


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in {"", "0", "false", "no", "off"}:
        return False
    if text in {"1", "true", "yes", "on"}:
        return True
    return default


def _split_glob_patterns(glob: str | None) -> list[str]:
    if not isinstance(glob, str) or not glob.strip():
        return []

    patterns: list[str] = []
    for raw_pattern in glob.split():
        if "{" in raw_pattern and "}" in raw_pattern:
            patterns.append(raw_pattern)
            continue
        patterns.extend(piece for piece in raw_pattern.split(",") if piece)
    return [pattern for pattern in patterns if pattern]


def _resolve_result_path(path_text: str, command_cwd: str) -> str:
    if os.path.isabs(path_text):
        return os.path.normpath(path_text)
    return os.path.normpath(expand_path(path_text, command_cwd))


def _type_matches(path: str, type_name: str | None) -> bool:
    if not type_name:
        return True
    normalized_type = type_name.strip().lower()
    if not normalized_type:
        return True

    suffix = Path(path).suffix.lower().lstrip(".")
    if not suffix:
        return False

    allowed = RIPGREP_TYPE_ALIASES.get(normalized_type)
    if allowed is None:
        return suffix == normalized_type
    return suffix in allowed


def _glob_matches(path: str, base_dir: str, glob_patterns: list[str]) -> bool:
    if not glob_patterns:
        return True

    file_path = Path(path)
    try:
        relative = _normalize_slashes(os.path.relpath(path, base_dir))
    except ValueError:
        relative = _normalize_slashes(file_path.name)

    basename = file_path.name
    return any(
        fnmatch.fnmatch(basename, pattern) or fnmatch.fnmatch(relative, pattern)
        for pattern in glob_patterns
    )


def _is_probably_binary(path: str) -> bool:
    try:
        with open(path, "rb") as handle:
            sample = handle.read(8192)
    except OSError:
        return True

    if not sample:
        return False
    if b"\x00" in sample:
        return True

    text_bytes = bytearray({7, 8, 9, 10, 12, 13, 27} | set(range(32, 127)))
    non_text = sample.translate(None, text_bytes)
    return len(non_text) / max(len(sample), 1) > 0.30


def _iter_searchable_files(search_root: str) -> Iterable[str]:
    root = Path(search_root)
    if root.is_file():
        yield str(root)
        return

    for current_root, dirs, filenames in os.walk(search_root):
        dirs[:] = [name for name in dirs if name not in VCS_DIRECTORIES_TO_EXCLUDE]
        root_path = Path(current_root)
        for filename in filenames:
            yield str(root_path / filename)


def _matches_deny_rule(
    file_path: str,
    permission_context: dict[str, Any] | None,
    cwd: str,
) -> bool:
    return (
        _matching_rule_for_read_input(
            os.path.normpath(file_path),
            permission_context,
            behavior="deny",
            cwd=cwd,
        )
        is not None
    )


def _extract_path_info_from_content_line(
    line: str,
    command_cwd: str,
) -> tuple[str, int] | None:
    if not line or line == "--":
        return None

    match = _CONTENT_WITH_LINE_RE.match(line)
    if match:
        return _resolve_result_path(match.group(1), command_cwd), len(match.group(1))

    for index, char in enumerate(line):
        if char not in {":", "-"}:
            continue
        if (
            os.name == "nt"
            and index == 1
            and len(line) > 2
            and line[2] in "\\/"
        ):
            continue
        candidate = line[:index]
        resolved = _resolve_result_path(candidate, command_cwd)
        if os.path.exists(resolved):
            return resolved, index

    return None


def _relativize_content_line(line: str, command_cwd: str) -> str:
    info = _extract_path_info_from_content_line(line, command_cwd)
    if info is None:
        return line
    absolute_path, prefix_length = info
    relative_path = to_relative_path(absolute_path, command_cwd)
    return relative_path + line[prefix_length:]


def _parse_count_line(
    line: str,
    command_cwd: str,
) -> tuple[str, int] | None:
    if not line:
        return None
    colon_index = line.rfind(":")
    if colon_index <= 0:
        return None
    try:
        count = int(line[colon_index + 1 :].strip())
    except ValueError:
        return None
    path_text = line[:colon_index]
    return _resolve_result_path(path_text, command_cwd), count


def _cleanup_content_separators(lines: list[str]) -> list[str]:
    cleaned: list[str] = []
    for line in lines:
        if line == "--":
            if cleaned and cleaned[-1] != "--":
                cleaned.append(line)
            continue
        cleaned.append(line)

    while cleaned and cleaned[0] == "--":
        cleaned.pop(0)
    while cleaned and cleaned[-1] == "--":
        cleaned.pop()
    return cleaned


def _ripgrep_timeout_seconds() -> int:
    raw = os.environ.get("CLAUDE_CODE_GLOB_TIMEOUT_SECONDS", "").strip()
    if raw:
        try:
            parsed = int(raw)
        except ValueError:
            parsed = 0
        if parsed > 0:
            return parsed
    return DEFAULT_TIMEOUT_SECONDS


def _run_ripgrep_once(
    executable: str,
    args: list[str],
    target: str,
    *,
    cwd: str,
    single_thread: bool = False,
) -> subprocess.CompletedProcess[str]:
    final_args = [executable]
    if single_thread:
        final_args.extend(["-j", "1"])
    final_args.extend(args)
    final_args.append(target)
    return subprocess.run(
        final_args,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_ripgrep_timeout_seconds(),
        check=False,
    )


def _run_ripgrep(args: list[str], target: str, *, cwd: str) -> list[str]:
    executable = shutil.which("rg") or shutil.which("ripgrep")
    if not executable:
        raise FileNotFoundError("ripgrep executable not found")

    def _execute(single_thread: bool = False) -> subprocess.CompletedProcess[str]:
        try:
            return _run_ripgrep_once(
                executable,
                args,
                target,
                cwd=cwd,
                single_thread=single_thread,
            )
        except subprocess.TimeoutExpired as exc:
            timeout_seconds = _ripgrep_timeout_seconds()
            raise RuntimeError(
                f"Ripgrep search timed out after {timeout_seconds} seconds. "
                "Try searching a more specific path or pattern."
            ) from exc

    completed = _execute(single_thread=False)
    stderr = (completed.stderr or "").strip()
    if (
        completed.returncode not in (0, 1)
        and (
            "os error 11" in (completed.stderr or "")
            or "Resource temporarily unavailable" in (completed.stderr or "")
        )
    ):
        completed = _execute(single_thread=True)
        stderr = (completed.stderr or "").strip()

    if completed.returncode not in (0, 1):
        raise RuntimeError(stderr or (completed.stdout or "").strip() or "ripgrep failed")

    return [
        line.rstrip("\r")
        for line in completed.stdout.splitlines()
        if line.rstrip("\r")
    ]


def _paths_overlap(first: str, second: str) -> bool:
    normalized_first = os.path.normcase(os.path.normpath(first))
    normalized_second = os.path.normcase(os.path.normpath(second))
    if normalized_first == normalized_second:
        return True
    if normalized_first.startswith(normalized_second + os.sep):
        return True
    if normalized_second.startswith(normalized_first + os.sep):
        return True
    return False


def _get_plugin_cache_root() -> str:
    override = os.environ.get("CLAUDE_CODE_PLUGIN_CACHE_DIR", "").strip()
    if override:
        return os.path.normpath(os.path.expanduser(override))
    return os.path.normpath(str(Path.home() / ".claude" / "plugins" / "cache"))


def _get_glob_exclusions_for_plugin_cache(search_path: str) -> list[str]:
    cache_root = _get_plugin_cache_root()
    if not os.path.isdir(cache_root) or not _paths_overlap(search_path, cache_root):
        return []

    exclusions: list[str] = []
    for current_root, dirs, filenames in os.walk(cache_root):
        relative_root = os.path.relpath(current_root, cache_root)
        depth = 0 if relative_root == "." else len(Path(relative_root).parts)
        if depth >= 4:
            dirs[:] = []
        if ".orphaned_at" not in filenames:
            continue
        version_dir = os.path.normpath(current_root)
        rel = _normalize_slashes(os.path.relpath(version_dir, cache_root))
        exclusions.append(f"!**/{rel}/**")
    return exclusions


def _search_with_python_fallback(
    *,
    pattern: str,
    absolute_path: str,
    output_mode: str,
    context_before: int,
    context_after: int,
    show_line_numbers: bool,
    case_insensitive: bool,
    type_name: str | None,
    glob_patterns: list[str],
    multiline: bool,
    permission_context: dict[str, Any] | None,
    cwd: str,
) -> list[str]:
    flags = re.MULTILINE
    if case_insensitive:
        flags |= re.IGNORECASE
    if multiline:
        flags |= re.DOTALL
    regex = re.compile(pattern, flags)
    glob_base_dir = absolute_path if os.path.isdir(absolute_path) else str(Path(absolute_path).parent)

    results: list[str] = []
    for file_path in _iter_searchable_files(absolute_path):
        normalized_path = os.path.normpath(file_path)
        if _matches_deny_rule(normalized_path, permission_context, cwd):
            continue
        if not _type_matches(normalized_path, type_name):
            continue
        if not _glob_matches(normalized_path, glob_base_dir, glob_patterns):
            continue
        if _is_probably_binary(normalized_path):
            continue

        try:
            text = Path(normalized_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if output_mode == "files_with_matches":
            if regex.search(text):
                results.append(normalized_path)
            continue

        if output_mode == "count":
            if multiline:
                count = sum(1 for _ in regex.finditer(text))
            else:
                count = sum(1 for line in text.splitlines() if regex.search(line))
            if count > 0:
                results.append(f"{normalized_path}:{count}")
            continue

        lines = text.splitlines()
        matched_indexes = [index for index, line in enumerate(lines) if regex.search(line)]

        if not matched_indexes and multiline:
            first_match = regex.search(text)
            if first_match is None:
                continue
            start_line = text[: first_match.start()].count("\n")
            end_line = text[: first_match.end()].count("\n")
            matched_indexes = list(range(start_line, end_line + 1))

        if not matched_indexes:
            continue

        ranges: list[tuple[int, int]] = []
        for match_index in matched_indexes:
            start = max(0, match_index - context_before)
            end = min(len(lines) - 1, match_index + context_after)
            if ranges and start <= ranges[-1][1] + 1:
                previous_start, previous_end = ranges[-1]
                ranges[-1] = (previous_start, max(previous_end, end))
            else:
                ranges.append((start, end))

        emitted_matches = set(matched_indexes)
        for range_index, (start, end) in enumerate(ranges):
            if range_index > 0:
                results.append("--")
            for line_index in range(start, end + 1):
                is_match_line = line_index in emitted_matches
                separator = ":" if is_match_line else "-"
                if show_line_numbers:
                    prefix = f"{normalized_path}{separator}{line_index + 1}{separator}"
                else:
                    prefix = f"{normalized_path}{separator}"
                results.append(prefix + lines[line_index])

    return results


class PythonGrepTool:
    name = GREP_TOOL_NAME
    search_hint = "search file contents with regex (ripgrep)"
    max_result_size_chars = 20_000
    strict = True
    input_schema = {
        # 搜索内容
        "pattern": "The regular expression pattern to search for in file contents",
        "path": (
            "File or directory to search in. Defaults to the current working "
            "directory."
        ),
        # 文件过滤
        "glob": 'Glob pattern to filter files (for example "*.py" or "*.{ts,tsx}")',
        """输出模式：
        content:返回匹配具体内容
        files_with_matches：匹配内容和文件名
        count：返回匹配次数
        """
        "output_mode": (
            'Output mode: "content", "files_with_matches", or "count". '
            'Defaults to "files_with_matches".'
        ),
       # 上下文行数（前N行，后N行，前后N行）
        "-B": "Number of lines to show before each match in content mode.",
        "-A": "Number of lines to show after each match in content mode.",
        "-C": "Alias for context in content mode.",
        "context": "Number of context lines before and after each match.",
      # 显示行号
        "-n": "Show line numbers in content mode. Defaults to true.",
       # 忽略大小写
      # 文件类型  "-i": "Case-insensitive search.",
        "type": "ripgrep file type filter such as js, ts, py, or go.",
        # 分页
        "head_limit": "Limit the number of returned lines or entries.",
        # 跳过前N行
        "offset": "Skip the first N lines or entries before limiting results.",
      # 分行搜索，启用多的话让正则1跨多行搜索
        "multiline": "Enable multiline matching.",
    }
    output_schema = {
        "mode": "content, files_with_matches, or count",
        "numFiles": "Number of files represented in the result payload",
        "filenames": "Matching filenames for files_with_matches mode",
        "content": "Rendered content or count lines for content/count modes",
        "numLines": "Number of returned content lines",
        "numMatches": "Number of returned matches in count mode",
        "appliedLimit": "The effective limit if truncation occurred",
        "appliedOffset": "The applied offset when non-zero",
    }

    async def description(self, _input_data: dict[str, Any] | None = None) -> str:
        return getDescription()

    async def prompt(self) -> str:
        return getDescription()

    def userFacingName(self, _input_data: dict[str, Any] | None = None) -> str:
        return "Search"

    def getToolUseSummary(self, input_data: dict[str, Any] | None) -> str | None:
        return getToolUseSummary(input_data)

    def getActivityDescription(self, input_data: dict[str, Any] | None) -> str:
        summary = self.getToolUseSummary(input_data)
        return f"Searching for {summary}" if summary else "Searching"

    def isConcurrencySafe(self, _input_data: dict[str, Any] | None = None) -> bool:
        return True

    def isReadOnly(self, _input_data: dict[str, Any] | None = None) -> bool:
        return True

    def toAutoClassifierInput(self, input_data: dict[str, Any]) -> str:
        path = input_data.get("path")
        pattern = str(input_data.get("pattern", ""))
        if isinstance(path, str) and path.strip():
            return f"{pattern} in {path}"
        return pattern

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
            if not Path(absolute_path).exists():
                suggestion = _suggest_path_under_cwd(absolute_path, cwd)
                message = (
                    f"Path does not exist: {path}. "
                    f"{FILE_NOT_FOUND_CWD_NOTE} {cwd}."
                )
                if suggestion:
                    message += f" Did you mean {suggestion}?"
                return {
                    "result": False,
                    "message": message,
                    "errorCode": 1,
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
        mode = str(output.get("mode", "files_with_matches"))
        if mode == "content":
            return str(output.get("content", "") or "")
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
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload = dict(args[0]) if args and isinstance(args[0], dict) else {}
        payload.update(kwargs)
        context = toolUseContext or ToolUseContext()
        permission_context = _get_permission_context(context)
        validation = await self.validateInput(payload, context)
        if not validation.get("result"):
            raise ValueError(str(validation.get("message", "Invalid grep request.")))

        pattern = str(payload.get("pattern", ""))
        path = payload.get("path")
        glob = payload.get("glob")
        type_name = payload.get("type")
        output_mode = str(payload.get("output_mode", "files_with_matches"))
        context_before = payload.get("-B")
        context_after = payload.get("-A")
        context_c = payload.get("-C")
        context_value = payload.get("context")
        show_line_numbers = _as_bool(payload.get("-n", True), True)
        case_insensitive = _as_bool(payload.get("-i", False), False)
        head_limit = payload.get("head_limit")
        offset = int(payload.get("offset", 0) or 0)
        multiline = _as_bool(payload.get("multiline", False), False)
        command_cwd = context.options.cwd
        absolute_path = expand_path(path, command_cwd) if path else command_cwd

        if output_mode not in {"content", "files_with_matches", "count"}:
            raise ValueError(
                'output_mode must be "content", "files_with_matches", or "count".'
            )

        before_value = (
            int(context_value)
            if context_value is not None
            else int(context_c)
            if context_c is not None
            else int(context_before)
            if context_before is not None
            else 0
        )
        after_value = (
            int(context_value)
            if context_value is not None
            else int(context_c)
            if context_c is not None
            else int(context_after)
            if context_after is not None
            else 0
        )
        glob_patterns = _split_glob_patterns(glob if isinstance(glob, str) else None)

        raw_results: list[str]
        rg_args = ["--hidden", "--max-columns", "500"]
        for directory in VCS_DIRECTORIES_TO_EXCLUDE:
            rg_args.extend(["--glob", f"!{directory}"])
        if multiline:
            rg_args.extend(["-U", "--multiline-dotall"])
        if case_insensitive:
            rg_args.append("-i")
        if output_mode == "files_with_matches":
            rg_args.append("-l")
        elif output_mode == "count":
            rg_args.append("-c")
        if output_mode == "content" and show_line_numbers:
            rg_args.append("-n")
        if output_mode == "content":
            if context_value is not None:
                rg_args.extend(["-C", str(int(context_value))])
            elif context_c is not None:
                rg_args.extend(["-C", str(int(context_c))])
            else:
                if context_before is not None:
                    rg_args.extend(["-B", str(int(context_before))])
                if context_after is not None:
                    rg_args.extend(["-A", str(int(context_after))])

        if pattern.startswith("-"):
            rg_args.extend(["-e", pattern])
        else:
            rg_args.append(pattern)

        if isinstance(type_name, str) and type_name.strip():
            rg_args.extend(["--type", type_name.strip()])
        for glob_pattern in glob_patterns:
            rg_args.extend(["--glob", glob_pattern])
        for exclusion in _get_glob_exclusions_for_plugin_cache(absolute_path):
            rg_args.extend(["--glob", exclusion])

        try:
            raw_results = _run_ripgrep(rg_args, absolute_path, cwd=command_cwd)
        except FileNotFoundError:
            raw_results = _search_with_python_fallback(
                pattern=pattern,
                absolute_path=absolute_path,
                output_mode=output_mode,
                context_before=before_value,
                context_after=after_value,
                show_line_numbers=show_line_numbers,
                case_insensitive=case_insensitive,
                type_name=type_name if isinstance(type_name, str) else None,
                glob_patterns=glob_patterns,
                multiline=multiline,
                permission_context=permission_context,
                cwd=command_cwd,
            )
        del abortController, getAppState

        if output_mode == "content":
            filtered_lines: list[str] = []
            for line in raw_results:
                path_info = _extract_path_info_from_content_line(line, command_cwd)
                if path_info is not None and _matches_deny_rule(
                    path_info[0],
                    permission_context,
                    command_cwd,
                ):
                    continue
                filtered_lines.append(_relativize_content_line(line, command_cwd))

            final_lines = _cleanup_content_separators(filtered_lines)
            limited = _apply_head_limit(final_lines, head_limit, offset)
            output = {
                "mode": "content",
                "numFiles": 0,
                "filenames": [],
                "content": "\n".join(limited["items"]),
                "numLines": len(limited["items"]),
            }
            if limited["appliedLimit"] is not None:
                output["appliedLimit"] = limited["appliedLimit"]
            if offset > 0:
                output["appliedOffset"] = offset
            return {"data": output}

        if output_mode == "count":
            filtered_count_lines: list[str] = []
            for line in raw_results:
                parsed = _parse_count_line(line, command_cwd)
                if parsed is None:
                    continue
                absolute_file, count = parsed
                if _matches_deny_rule(absolute_file, permission_context, command_cwd):
                    continue
                relative_file = to_relative_path(absolute_file, command_cwd)
                filtered_count_lines.append(f"{relative_file}:{count}")

            limited = _apply_head_limit(filtered_count_lines, head_limit, offset)
            total_matches = 0
            file_count = 0
            for line in limited["items"]:
                parsed = _parse_count_line(line, command_cwd)
                if parsed is None:
                    continue
                total_matches += parsed[1]
                file_count += 1

            output = {
                "mode": "count",
                "numFiles": file_count,
                "filenames": [],
                "content": "\n".join(limited["items"]),
                "numMatches": total_matches,
            }
            if limited["appliedLimit"] is not None:
                output["appliedLimit"] = limited["appliedLimit"]
            if offset > 0:
                output["appliedOffset"] = offset
            return {"data": output}

        absolute_matches: list[str] = []
        for entry in raw_results:
            absolute_file = _resolve_result_path(entry, command_cwd)
            if _matches_deny_rule(absolute_file, permission_context, command_cwd):
                continue
            absolute_matches.append(absolute_file)

        def _mtime(path_value: str) -> float:
            try:
                return os.path.getmtime(path_value)
            except OSError:
                return 0.0

        if os.environ.get("NODE_ENV") == "test":
            sorted_matches = sorted(absolute_matches)
        else:
            sorted_matches = sorted(
                absolute_matches,
                key=lambda item: (-_mtime(item), item),
            )

        limited = _apply_head_limit(sorted_matches, head_limit, offset)
        filenames = [
            to_relative_path(path_value, command_cwd)
            for path_value in limited["items"]
        ]
        output = {
            "mode": "files_with_matches",
            "numFiles": len(filenames),
            "filenames": filenames,
        }
        if limited["appliedLimit"] is not None:
            output["appliedLimit"] = limited["appliedLimit"]
        if offset > 0:
            output["appliedOffset"] = offset
        return {"data": output}

    def mapToolResultToToolResultBlockParam(
        self,
        output: dict[str, Any],
        tool_use_id: str,
    ) -> dict[str, Any]:
        mode = str(output.get("mode", "files_with_matches"))
        num_files = int(output.get("numFiles", 0) or 0)
        filenames = [
            str(item)
            for item in output.get("filenames", [])
            if isinstance(item, str)
        ]
        content = str(output.get("content", "") or "")
        num_matches = int(output.get("numMatches", 0) or 0)
        applied_limit = output.get("appliedLimit")
        applied_offset = output.get("appliedOffset")
        limit_info = _format_limit_info(
            int(applied_limit) if applied_limit is not None else None,
            int(applied_offset) if applied_offset is not None else None,
        )

        if mode == "content":
            result_content = content or "No matches found"
            if limit_info:
                result_content += (
                    f"\n\n[Showing results with pagination = {limit_info}]"
                )
            return {
                "tool_use_id": tool_use_id,
                "type": "tool_result",
                "content": result_content,
            }

        if mode == "count":
            raw_content = content or "No matches found"
            summary = (
                f"\n\nFound {num_matches} total {_plural(num_matches, 'occurrence')} "
                f"across {num_files} {_plural(num_files, 'file')}."
            )
            if limit_info:
                summary += f" with pagination = {limit_info}"
            return {
                "tool_use_id": tool_use_id,
                "type": "tool_result",
                "content": raw_content + summary,
            }

        if num_files == 0:
            return {
                "tool_use_id": tool_use_id,
                "type": "tool_result",
                "content": "No files found",
            }

        result = (
            f"Found {num_files} {_plural(num_files, 'file')}"
            f"{f' {limit_info}' if limit_info else ''}\n"
            + "\n".join(filenames)
        )
        return {
            "tool_use_id": tool_use_id,
            "type": "tool_result",
            "content": result,
        }


GrepTool = PythonGrepTool()

__all__ = [
    "DEFAULT_HEAD_LIMIT",
    "GrepTool",
    "PythonGrepTool",
]
