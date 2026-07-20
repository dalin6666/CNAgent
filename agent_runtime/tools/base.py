from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..errors import PathOutsideWorkspaceError
from ..schemas import FileSnapshot, SessionState, ToolResult, ToolStreamDelta


@dataclass(slots=True)
class ToolRuntimeContext:
    session: SessionState
    working_directory: str  # 工作目录，相对目录的起点
    config: Any
    telemetry: Any
    interrupt_controller: Any
    workspace_root: str | Path | None = None
    _workspace_root: Path = field(init=False, repr=False)  # 初始化后确认的根工作空间目录

    # data类初始化
    def __post_init__(self) -> None:
        root = Path(self.workspace_root or self.working_directory).expanduser().resolve(
            strict=False
        )
        current = Path(self.working_directory).expanduser().resolve(strict=False)
        if not current.is_relative_to(root):
            raise PathOutsideWorkspaceError(
                f"Working directory is outside the workspace: {current}. "
                f"Workspace root: {root}"
            )
        self._workspace_root = root
        self.workspace_root = str(root)
        self.working_directory = str(current)

    def resolve_path(self, path: str | Path) -> Path:  # 用户请求访问的目标目录
        root = self._workspace_root
        current = Path(self.working_directory).expanduser().resolve(strict=False)
        candidate = Path(path).expanduser()  # 展开用户的主目录符号~
        candidate = candidate if candidate.is_absolute() else current / candidate
        resolved = candidate.resolve(strict=False)  # 消除.、处理..并解析符号链接

        # 必须酰拼接，在resolve(),然后检查
        if not resolved.is_relative_to(root):
            raise PathOutsideWorkspaceError(
                f"Path is outside the workspace: {path!s}. "
                # path!s输出绝对内容
                f"Workspace root: {root}"
            )
        return resolved

    def set_working_directory(self, path: str | Path) -> str:
        resolved = str(self.resolve_path(path))
        self.working_directory = resolved
        self.session.metadata["working_directory"] = resolved
        return resolved

    def is_interrupted(self) -> bool:
        controller = self.interrupt_controller
        return bool(
            getattr(controller, "interrupted", False)
            or getattr(controller, "aborted", False)
        )

    def file_snapshot(self, path: str | Path) -> FileSnapshot | None:
        return FileSnapshot.from_path(str(self.resolve_path(path)))

    def remember_file_snapshot(self, path: str | Path) -> FileSnapshot | None:
        snapshot = self.file_snapshot(path)
        if snapshot is not None:
            self.session.file_snapshots[str(Path(snapshot.path).resolve())] = snapshot
        return snapshot


class BaseTool(ABC):
    name = "base_tool"
    description = ""
    permission_group = "read"
    aliases: tuple[str, ...] = ()
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}
    output_schema: dict[str, Any] = {"type": "object", "properties": {}}
    strict = False
    should_defer = False
    requires_user_interaction = False
    is_enabled = True
    max_result_size_chars: int | None = None

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "aliases": list(self.aliases),
            "description": self.description,
            "permission_group": self.permission_group,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "strict": self.strict,
            "should_defer": self.should_defer,
            "requires_user_interaction": self.requires_user_interaction,
            "is_enabled": self.is_enabled,
            "max_result_size_chars": self.max_result_size_chars,
        }

    def summarize(self, arguments: dict[str, Any]) -> str:
        return f"{self.name}({arguments})"

    def resolve_tool_call_id(self, arguments: dict[str, Any]) -> str:
        return str(arguments.get("_tool_call_id", ""))

    def truncate_text(self, text: str, limit: int | None = None) -> str:
        effective_limit = (
            self.max_result_size_chars if limit is None else limit
        )
        if effective_limit in (None, 0) or len(text) <= effective_limit:
            return text
        if effective_limit <= 3:
            return text[:effective_limit]
        return text[: effective_limit - 3] + "..."

    def build_result(
        self,
        arguments: dict[str, Any],
        *,
        output: Any,
        summary: str | None = None,
        is_error: bool = False,
    ) -> ToolResult:
        rendered_summary = summary if summary is not None else self.summarize(arguments)
        return ToolResult(
            tool_call_id=self.resolve_tool_call_id(arguments),
            name=self.name,
            output=output,
            is_error=is_error,
            summary=self.truncate_text(rendered_summary),
        )

    @abstractmethod
    async def run(
        self,
        arguments: dict[str, Any],
        context: ToolRuntimeContext,
    ) -> ToolResult:
        raise NotImplementedError

    async def stream(
        self,
        arguments: dict[str, Any],
        context: ToolRuntimeContext,
    ) -> AsyncIterator[ToolStreamDelta | ToolResult]:
        yield await self.run(arguments, context)
