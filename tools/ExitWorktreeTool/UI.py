from __future__ import annotations

from typing import Any

__all__ = ["renderToolResultMessage", "renderToolUseMessage"]


def renderToolUseMessage(input_data: dict[str, Any] | None = None, *_args: Any, **_kwargs: Any) -> str:
    action = (input_data or {}).get("action")
    if action == "remove":
        return "Removing worktree..."
    return "Exiting worktree..."


def renderToolResultMessage(output: dict[str, Any], *_args: Any, **_kwargs: Any) -> str:
    return str(output.get("message", "")).strip()
