from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .._runtime import STATE_ROOT, to_relative_path

MAX_LINES_TO_RENDER = 10
EOL = "\n"
PLAN_ROOT = STATE_ROOT / "plans"


def countLines(content: str) -> int:
    parts = content.split(EOL)
    return len(parts) - 1 if content.endswith(EOL) else len(parts)


def _display_path(file_path: str, verbose: bool = False) -> str:
    if verbose:
        return file_path
    return to_relative_path(file_path)


def userFacingName(input_data: dict[str, Any] | None = None) -> str:
    file_path = str((input_data or {}).get("file_path", ""))
    if file_path.startswith(str(PLAN_ROOT)):
        return "Updated plan"
    return "Write"


def isResultTruncated(output: dict[str, Any]) -> bool:
    if str(output.get("type", "")) != "create":
        return False
    content = str(output.get("content", ""))
    position = 0
    for _ in range(MAX_LINES_TO_RENDER):
        position = content.find(EOL, position)
        if position == -1:
            return False
        position += 1
    return position < len(content)


def getToolUseSummary(input_data: dict[str, Any] | None = None) -> str | None:
    file_path = str((input_data or {}).get("file_path", "")).strip()
    return file_path or None


def renderToolUseMessage(
    input_data: dict[str, Any] | None = None,
    *,
    verbose: bool = False,
) -> str | None:
    file_path = str((input_data or {}).get("file_path", "")).strip()
    if not file_path:
        return None
    if file_path.startswith(str(PLAN_ROOT)):
        return ""
    return _display_path(file_path, verbose)


def renderToolUseRejectedMessage(
    input_data: dict[str, Any] | None = None,
    *,
    style: str | None = None,
    verbose: bool = False,
) -> str:
    del style
    file_path = str((input_data or {}).get("file_path", "")).strip()
    content = str((input_data or {}).get("content", ""))
    if not file_path:
        return "Write rejected"
    first_line = content.splitlines()[0] if content else ""
    prefix = f"Write rejected for {_display_path(file_path, verbose)}"
    return f"{prefix}: {first_line}" if first_line else prefix


def renderToolUseErrorMessage(
    result: Any = None,
    *,
    verbose: bool = False,
) -> str:
    if not verbose:
        return "Error writing file"
    return f"Error writing file: {result}" if result else "Error writing file"


def renderToolResultMessage(
    output: dict[str, Any],
    *_args: Any,
    style: str | None = None,
    verbose: bool = False,
    **_kwargs: Any,
) -> str:
    del style
    output_type = str(output.get("type", ""))
    file_path = str(output.get("filePath", ""))
    content = str(output.get("content", ""))

    if output_type == "create":
        num_lines = countLines(content)
        header = f"Wrote {num_lines} lines to {_display_path(file_path, verbose)}"
        if verbose or not isResultTruncated(output):
            preview = content
        else:
            preview = "\n".join(content.split("\n")[:MAX_LINES_TO_RENDER])
        return header if not preview else f"{header}\n{preview}"

    patch = output.get("structuredPatch") or []
    if patch:
        patch_lines: list[str] = []
        for hunk in patch:
            patch_lines.extend(str(line) for line in hunk.get("lines", []))
        preview = "\n".join(patch_lines)
        return (
            f"Updated {_display_path(file_path, verbose)}\n{preview}"
            if preview
            else f"Updated {_display_path(file_path, verbose)}"
        )

    if file_path:
        return f"Updated {_display_path(file_path, verbose)}"
    return "File updated"


__all__ = [
    "countLines",
    "getToolUseSummary",
    "isResultTruncated",
    "renderToolResultMessage",
    "renderToolUseErrorMessage",
    "renderToolUseMessage",
    "renderToolUseRejectedMessage",
    "userFacingName",
]
