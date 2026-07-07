from __future__ import annotations

from typing import Any

__all__ = ["renderToolResultMessage", "renderToolUseMessage"]


def renderToolUseMessage(*_args: Any, **_kwargs: Any) -> str:
    return "Creating worktree..."


def renderToolResultMessage(output: dict[str, Any], *_args: Any, **_kwargs: Any) -> str:
    branch = output.get("worktreeBranch")
    path = output.get("worktreePath", "")
    if branch:
        return f"Switched to worktree on branch {branch}\n{path}".strip()
    return f"Switched to worktree\n{path}".strip()
