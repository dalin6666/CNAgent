from __future__ import annotations

import fnmatch
import os
import time
from pathlib import Path
from typing import Any

from ..schemas import ToolResult, ToolStreamDelta
from .base import BaseTool, ToolRuntimeContext

DEFAULT_MAX_RESULTS = 100
DEFAULT_OFFSET = 0
SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".jj",
    ".sl",
    ".svn",
    "__pycache__",
    "node_modules",
}


def _normalize_pattern(value: str) -> str:
    return value.replace("\\", "/")


def _matches_pattern(path: Path, pattern: str, base_path: Path) -> bool:
    normalized_pattern = _normalize_pattern(pattern)
    relative = _normalize_pattern(str(path.relative_to(base_path)))
    return fnmatch.fnmatch(path.name, normalized_pattern) or fnmatch.fnmatch(
        relative,
        normalized_pattern,
    )


def _iter_files(
    base_path: Path,
    *,
    include_hidden: bool,
    follow_symlinks: bool,
    context: ToolRuntimeContext,
):
    if base_path.is_file():
        yield base_path
        return

    for root, dirs, filenames in os.walk(base_path, followlinks=follow_symlinks):
        if context.is_interrupted():
            break
        if include_hidden:
            dirs[:] = [name for name in dirs if name not in SKIP_DIR_NAMES]
        else:
            dirs[:] = [
                name
                for name in dirs
                if name not in SKIP_DIR_NAMES and not name.startswith(".")
            ]
            filenames = [name for name in filenames if not name.startswith(".")]
        root_path = Path(root)
        for filename in filenames:
            yield root_path / filename


class GlobSearchTool(BaseTool):
    name = "glob_search"
    description = "Recursively search files by glob pattern."
    permission_group = "read"
    aliases = ("find_files",)
    strict = True
    max_result_size_chars = 20_000
    output_schema = {
        "type": "object",
        "properties": {
            "base_path": {"type": "string"},
            "pattern": {"type": "string"},
            "matches": {"type": "array"},
            "count": {"type": "integer"},
            "returned_count": {"type": "integer"},
            "offset": {"type": "integer"},
            "truncated": {"type": "boolean"},
            "scanned_files": {"type": "integer"},
            "elapsed_ms": {"type": "integer"},
        },
    }
    input_schema = {
        "type": "object",
        "properties": {
            "base_path": {"type": "string"},
            "pattern": {"type": "string"},
            "max_results": {"type": "integer"},
            "offset": {"type": "integer"},
            "include_hidden": {"type": "boolean"},
            "follow_symlinks": {"type": "boolean"},
        },
        "required": ["pattern"],
    }

    def summarize(self, arguments: dict[str, object]) -> str:
        pattern = arguments.get("pattern", "*")
        base_path = arguments.get("base_path", ".")
        return f"glob_search(pattern={pattern}, base_path={base_path})"

    async def stream(self, arguments: dict[str, object], context: ToolRuntimeContext):
        started_at = time.perf_counter()
        pattern = str(arguments.get("pattern", "*")).strip() or "*"
        raw_base_path = str(arguments.get("base_path", context.working_directory)).strip()
        base_path = context.resolve_path(raw_base_path or context.working_directory)
        max_results = max(int(arguments.get("max_results", DEFAULT_MAX_RESULTS)), 1)
        offset = max(int(arguments.get("offset", DEFAULT_OFFSET)), 0)
        include_hidden = bool(arguments.get("include_hidden", True))
        follow_symlinks = bool(arguments.get("follow_symlinks", False))

        if not base_path.exists():
            raise ValueError(f"Base path does not exist: {raw_base_path or base_path}")

        scanned_files = 0
        total_matches = 0
        yielded_matches = 0
        truncated = False
        matches: list[str] = []

        for candidate in _iter_files(
            base_path,
            include_hidden=include_hidden,
            follow_symlinks=follow_symlinks,
            context=context,
        ):
            if context.is_interrupted():
                break
            scanned_files += 1
            if not candidate.is_file():
                continue
            if not _matches_pattern(candidate, pattern, base_path.parent if base_path.is_file() else base_path):
                continue

            total_matches += 1
            if total_matches <= offset:
                continue
            if yielded_matches >= max_results:
                truncated = True
                continue

            relative_root = base_path.parent if base_path.is_file() else base_path
            relative = str(candidate.relative_to(relative_root))
            matches.append(relative)
            yielded_matches += 1
            yield ToolStreamDelta(text=relative, data={"path": relative})

        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        yield self.build_result(
            arguments,
            output={
                "base_path": str(base_path),
                "pattern": pattern,
                "matches": matches,
                "count": total_matches,
                "returned_count": len(matches),
                "offset": offset,
                "truncated": truncated,
                "scanned_files": scanned_files,
                "elapsed_ms": elapsed_ms,
            },
            summary=f"Found {total_matches} file(s), returned {len(matches)}.",
        )

    async def run(
        self,
        arguments: dict[str, object],
        context: ToolRuntimeContext,
    ) -> ToolResult:
        last_result: ToolResult | None = None
        async for item in self.stream(arguments, context):
            if isinstance(item, ToolResult):
                last_result = item
        assert last_result is not None
        return last_result
