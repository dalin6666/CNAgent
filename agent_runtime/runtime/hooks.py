from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from ..schemas import SessionState

StopHook = Callable[["StopHookContext"], dict[str, Any] | None | Awaitable[dict[str, Any] | None]]


@dataclass(slots=True)
class StopHookContext:
    session: SessionState
    final_text: str
    stop_reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


class StopHookManager:
    def __init__(self) -> None:
        self._hooks: list[StopHook] = []

    def register(self, hook: StopHook) -> None:
        self._hooks.append(hook)

    async def run_all(self, context: StopHookContext) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for hook in self._hooks:
            value = hook(context)
            if inspect.isawaitable(value):
                value = await value
            if value:
                results.append(value)
        return results
