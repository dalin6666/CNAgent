from __future__ import annotations

from typing import Any

from .._runtime import list_git_operations, now_ms, record_git_operation


def trackGitOperation(operation: str, path: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return record_git_operation({'operation': operation, 'path': path, 'metadata': metadata or {}, 'timestamp': now_ms()})


def listTrackedGitOperations() -> list[dict[str, Any]]:
    return list_git_operations()
