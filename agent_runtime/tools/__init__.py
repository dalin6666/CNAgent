from __future__ import annotations

from .base import BaseTool, ToolRuntimeContext
from .builtin_echo import EchoTool
from .builtin_glob_search import GlobSearchTool
from .builtin_read_file import ReadFileTool
from .legacy_adapter import LegacyToolAdapter, register_legacy_tool_adapters
from .permissions import PermissionManager
from .registry import ToolRegistry


def create_builtin_tools() -> list[BaseTool]:
    return [EchoTool(), GlobSearchTool(), ReadFileTool()]


def create_tool_registry(*, include_legacy: bool = False) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_many(create_builtin_tools())
    if include_legacy:
        register_legacy_tool_adapters(registry)
    return registry


__all__ = [
    "BaseTool",
    "EchoTool",
    "GlobSearchTool",
    "LegacyToolAdapter",
    "PermissionManager",
    "ReadFileTool",
    "ToolRegistry",
    "ToolRuntimeContext",
    "create_builtin_tools",
    "create_tool_registry",
    "register_legacy_tool_adapters",
]
