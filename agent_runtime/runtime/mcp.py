from __future__ import annotations

import inspect
from typing import Any, Callable

from ..tools.base import BaseTool

ToolFactory = Callable[[str], list[BaseTool] | Any]


class MCPToolDiscovery:
    def __init__(self) -> None:
        self._factories: dict[str, ToolFactory] = {}

    def register_client(self, name: str, factory: ToolFactory) -> None:
        self._factories[name] = factory

    async def discover(self, query: str) -> list[BaseTool]:
        discovered: list[BaseTool] = []
        for factory in self._factories.values():
            result = factory(query)
            if inspect.isawaitable(result):
                result = await result
            discovered.extend(result or [])
        return discovered
