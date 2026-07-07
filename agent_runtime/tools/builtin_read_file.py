from __future__ import annotations

from pathlib import Path
from typing import Any

from ..schemas import ToolResult
from .base import BaseTool, ToolRuntimeContext

DEFAULT_LINE_LIMIT = 120
DEFAULT_MAX_CHARS = 50_000
BINARY_SUFFIXES = {
    ".7z",
    ".bin",
    ".class",
    ".dll",
    ".dylib",
    ".exe",
    ".gz",
    ".jar",
    ".lib",
    ".o",
    ".obj",
    ".pdf",
    ".pyc",
    ".so",
    ".tar",
    ".zip",
}


def _looks_binary(path: Path, content: bytes) -> bool:
    if path.suffix.lower() in BINARY_SUFFIXES:
        return True
    return b"\x00" in content


def _coerce_line_window(arguments: dict[str, Any]) -> tuple[int, int]:
    if "start_line" in arguments or "end_line" in arguments:
        start_line = max(int(arguments.get("start_line", 1)), 1)
        end_line = max(int(arguments.get("end_line", start_line + DEFAULT_LINE_LIMIT - 1)), start_line)
        return start_line, end_line

    offset = max(int(arguments.get("offset", 1)), 1)
    limit = arguments.get("limit")
    if limit is None:
        return offset, offset + DEFAULT_LINE_LIMIT - 1
    line_limit = max(int(limit), 1)
    return offset, offset + line_limit - 1


def _build_numbered_lines(lines: list[str], start_line: int, max_chars: int) -> tuple[str, int, bool]:
    rendered_lines: list[str] = []
    rendered_length = 0
    returned_lines = 0
    truncated = False

    for index, line in enumerate(lines, start=start_line):
        candidate = f"{index}\t{line}"
        additional_length = len(candidate) + (1 if rendered_lines else 0)
        if rendered_lines and rendered_length + additional_length > max_chars:
            truncated = True
            break
        if not rendered_lines and len(candidate) > max_chars:
            rendered_lines.append(candidate[:max_chars])
            returned_lines += 1
            truncated = True
            break
        rendered_lines.append(candidate)
        rendered_length += additional_length
        returned_lines += 1

    return "\n".join(rendered_lines), returned_lines, truncated


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read a text file, optionally with a line range."
    permission_group = "read"
    aliases = ("open_file",)
    strict = True
    max_result_size_chars = 50_000
    output_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer"},
            "end_line": {"type": "integer"},
            "returned_lines": {"type": "integer"},
            "content": {"type": "string"},
            "total_lines": {"type": "integer"},
            "truncated": {"type": "boolean"},
            "size_bytes": {"type": "integer"},
        },
    }
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "start_line": {"type": "integer"},
            "end_line": {"type": "integer"},
            "offset": {"type": "integer"},
            "limit": {"type": "integer"},
            "max_chars": {"type": "integer"},
        },
        "required": ["path"],
    }

    async def run(
        self,
        arguments: dict[str, object],
        context: ToolRuntimeContext,
    ) -> ToolResult:
        raw_path = str(arguments.get("path", "")).strip()
        if not raw_path:
            raise ValueError("path is required.")

        path = context.resolve_path(raw_path)
        if not path.exists():
            raise ValueError(
                f"File does not exist: {raw_path}. Current working directory: {context.working_directory}"
            )
        if path.is_dir():
            raise ValueError(f"Path is a directory, not a file: {raw_path}")

        start_line, end_line = _coerce_line_window(arguments)
        max_chars = max(int(arguments.get("max_chars", DEFAULT_MAX_CHARS)), 1)
        raw_bytes = path.read_bytes()
        if _looks_binary(path, raw_bytes[:4096]):
            raise ValueError(f"Binary files are not supported by read_file: {raw_path}")

        content = raw_bytes.decode("utf-8", errors="replace")
        lines = content.splitlines()
        selection = lines[start_line - 1 : end_line]
        numbered, returned_lines, truncated = _build_numbered_lines(
            selection,
            start_line,
            max_chars,
        )
        context.remember_file_snapshot(path)

        return self.build_result(
            arguments,
            output={
                "path": str(path),
                "start_line": start_line,
                "end_line": end_line,
                "returned_lines": returned_lines,
                "content": numbered,
                "total_lines": len(lines),
                "truncated": truncated or end_line < len(lines),
                "size_bytes": len(raw_bytes),
            },
            summary=f"Read {returned_lines} line(s) from {path.name}.",
        )
