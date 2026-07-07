from __future__ import annotations

from typing import Any


def BackgroundHint() -> str:
    return "Command is still running. You can continue while output is being collected."


def renderToolUseMessage(input_data: dict[str, Any] | None = None) -> str:
    command = str((input_data or {}).get("command", "")).strip()
    return f"Running: {command}" if command else "Running shell command"


def renderToolUseProgressMessage(progress: dict[str, Any] | None = None) -> str:
    if not progress:
        return "Command in progress"
    output = str(progress.get("output", "")).strip()
    return output or "Command in progress"


def renderToolUseQueuedMessage(input_data: dict[str, Any] | None = None) -> str:
    command = str((input_data or {}).get("command", "")).strip()
    return f"Queued: {command}" if command else "Command queued"


def renderToolResultMessage(output: dict[str, Any] | None = None) -> str:
    output = output or {}
    stdout = str(output.get("stdout", "")).strip()
    stderr = str(output.get("stderr", "")).strip()
    background_task_id = output.get("backgroundTaskId")
    if background_task_id:
        return f"Background task started: {background_task_id}"
    if stderr and stdout:
        return f"{stdout}\n{stderr}"
    return stdout or stderr or "Done"


def renderToolUseErrorMessage(error: Any = None) -> str:
    return f"Command failed: {error}" if error else "Command failed"


__all__ = [
    "BackgroundHint",
    "renderToolResultMessage",
    "renderToolUseErrorMessage",
    "renderToolUseMessage",
    "renderToolUseProgressMessage",
    "renderToolUseQueuedMessage",
]
