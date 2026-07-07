from __future__ import annotations

from typing import Iterable

from .base import BaseTool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._aliases: dict[str, str] = {}
        self._tool_aliases: dict[str, set[str]] = {}

    @staticmethod
    def _normalize_name(name: str) -> str:
        normalized = str(name).strip()
        if not normalized:
            raise ValueError("Tool name must be a non-empty string.")
        return normalized

    def _drop_aliases_for(self, tool_name: str) -> None:
        aliases = self._tool_aliases.pop(tool_name, set())
        for alias in aliases:
            self._aliases.pop(alias, None)

    def register(self, tool: BaseTool) -> BaseTool:
        canonical_name = self._normalize_name(tool.name)
        if canonical_name in self._tools:
            self._drop_aliases_for(canonical_name)
        self._tools[canonical_name] = tool
        registered_aliases: set[str] = set()
        for alias in getattr(tool, "aliases", ()) or ():
            normalized_alias = str(alias).strip()
            if not normalized_alias or normalized_alias == canonical_name:
                continue
            if normalized_alias in self._tools and normalized_alias != canonical_name:
                continue
            self._aliases[normalized_alias] = canonical_name
            registered_aliases.add(normalized_alias)
        self._tool_aliases[canonical_name] = registered_aliases
        return tool

    def register_many(self, tools: Iterable[BaseTool]) -> list[BaseTool]:
        registered: list[BaseTool] = []
        for tool in tools:
            registered.append(self.register(tool))
        return registered

    def get(self, name: str) -> BaseTool | None:
        try:
            normalized = self._normalize_name(name)
        except ValueError:
            return None
        canonical = self._aliases.get(normalized, normalized)
        return self._tools.get(canonical)

    def require(self, name: str) -> BaseTool:
        tool = self.get(name)
        if tool is None:
            raise KeyError(f"Unknown tool: {name}")
        return tool

    def remove(self, name: str) -> BaseTool | None:
        try:
            normalized = self._normalize_name(name)
        except ValueError:
            return None
        canonical = self._aliases.pop(normalized, normalized)
        tool = self._tools.pop(canonical, None)
        if tool is not None:
            self._drop_aliases_for(canonical)
        return tool

    def has(self, name: str) -> bool:
        return self.get(name) is not None

    def describe_tools(self) -> list[dict]:
        return [tool.schema() for tool in self._tools.values()]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def aliases(self) -> dict[str, str]:
        return dict(sorted(self._aliases.items()))

    def items(self) -> list[tuple[str, BaseTool]]:
        return list(self._tools.items())

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str):
            return False
        try:
            return self.has(name)
        except ValueError:
            return False

    def __len__(self) -> int:
        return len(self._tools)
