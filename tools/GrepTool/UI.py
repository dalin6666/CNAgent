from __future__ import annotations

from pathlib import Path
from typing import Any

from ..GlobTool.GlobTool import FILE_NOT_FOUND_CWD_NOTE

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


def _plural(count: int, noun: str) -> str:
    if count == 1:
        return noun
    if noun.endswith(("s", "x", "z", "ch", "sh")):
        return f"{noun}es"
    if noun.endswith("y") and len(noun) > 1 and noun[-2].lower() not in "aeiou":
        return noun[:-1] + "ies"
    return f"{noun}s"


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

    parts = [f'pattern: "{pattern}"']
    if path:
        shown_path = path if verbose else _display_path(path)
        parts.append(f'path: "{shown_path}"')
    return ", ".join(parts)


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
    *_args: Any,
    verbose: bool = False,
    **_kwargs: Any,
) -> str:
    payload = output or {}
    mode = str(payload.get("mode", "files_with_matches"))
    num_files = int(payload.get("numFiles", 0) or 0)
    filenames = [
        str(item)
        for item in payload.get("filenames", [])
        if isinstance(item, str)
    ]
    content = str(payload.get("content", "") or "")
    num_lines = int(payload.get("numLines", 0) or 0)
    num_matches = int(payload.get("numMatches", 0) or 0)

    if mode == "content":
        summary = f"Found {num_lines} {_plural(num_lines, 'line')}"
        if verbose and content:
            return f"{summary}\n{content}"
        return summary

    if mode == "count":
        summary = (
            f"Found {num_matches} {_plural(num_matches, 'match')} across "
            f"{num_files} {_plural(num_files, 'file')}"
        )
        if verbose and content:
            return f"{summary}\n{content}"
        return summary

    summary = f"Found {num_files} {_plural(num_files, 'file')}"
    if verbose and filenames:
        return summary + "\n" + "\n".join(filenames)
    return summary if num_files > 0 else "No files found"


def getToolUseSummary(input_data: dict[str, Any] | None) -> str | None:
    pattern = str((input_data or {}).get("pattern", "")).strip()
    return _truncate(pattern) if pattern else None


__all__ = [
    "getToolUseSummary",
    "renderToolResultMessage",
    "renderToolUseErrorMessage",
    "renderToolUseMessage",
]
