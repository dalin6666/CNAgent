from __future__ import annotations

from pathlib import Path
from typing import Any

FILE_NOT_FOUND_CWD_NOTE = "Note: your current working directory is"
TOOL_SUMMARY_MAX_LENGTH = 50


def _truncate(value: str, limit: int = TOOL_SUMMARY_MAX_LENGTH) -> str:
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[: limit - 3] + "..."


def _display_path(path: str) -> str:
    try:
        cwd = Path.cwd().resolve()
        target = Path(path).resolve()
        return str(target.relative_to(cwd))
    except (OSError, ValueError):
        return path


def userFacingName() -> str:
    return "Search"


def renderToolUseMessage(
    input_data: dict[str, Any] | None = None,
    *,
    verbose: bool = False,
) -> str | None:
    payload = input_data or {}
    pattern = str(payload.get("pattern", "")).strip()
    path = str(payload.get("path", "")).strip()
    if not pattern:
        return None
    if not path:
        return f'pattern: "{pattern}"'
    shown_path = path if verbose else _display_path(path)
    return f'pattern: "{pattern}", path: "{shown_path}"'


def renderToolUseErrorMessage(
    result: Any,
    *,
    verbose: bool = False,
) -> str:
    if not verbose and isinstance(result, str):
        if FILE_NOT_FOUND_CWD_NOTE in result:
            return "File not found"
        return "Error searching files"
    return str(result)


def renderToolResultMessage(
    output: dict[str, Any] | None = None,
    *,
    verbose: bool = False,
) -> str:
    del verbose
    payload = output or {}
    num_files = int(payload.get("numFiles", 0) or 0)
    duration_ms = int(payload.get("durationMs", 0) or 0)
    if num_files == 0:
        return "No files found"
    suffix = "s" if num_files != 1 else ""
    return f"Found {num_files} file{suffix} in {duration_ms}ms"


def getToolUseSummary(input_data: dict[str, Any] | None) -> str | None:
    pattern = str((input_data or {}).get("pattern", "")).strip()
    return _truncate(pattern) if pattern else None


__all__ = [
    "getToolUseSummary",
    "renderToolResultMessage",
    "renderToolUseErrorMessage",
    "renderToolUseMessage",
    "userFacingName",
]
