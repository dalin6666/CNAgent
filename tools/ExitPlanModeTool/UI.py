from __future__ import annotations

from typing import Any

from .._session_state import read_plan

__all__ = [
    "renderToolResultMessage",
    "renderToolUseMessage",
    "renderToolUseRejectedMessage",
]


def renderToolUseMessage(*_args: Any, **_kwargs: Any) -> None:
    return None


def renderToolResultMessage(output: dict[str, Any], *_args: Any, **_kwargs: Any) -> str:
    plan = str(output.get("plan") or "")
    file_path = str(output.get("filePath") or "")
    if not plan.strip():
        return "Exited plan mode"
    if output.get("awaitingLeaderApproval"):
        lines = ["Plan submitted for team lead approval"]
        if file_path:
            lines.append(f"Plan file: {file_path}")
        lines.append("Waiting for team lead to review and approve...")
        return "\n".join(lines)
    lines = ["User approved Claude's plan"]
    if file_path:
        lines.append(f"Plan saved to: {file_path}")
    lines.append(plan)
    return "\n".join(lines)


def renderToolUseRejectedMessage(
    output: dict[str, Any] | None = None,
    *_args: Any,
    app_state: Any = None,
    **_kwargs: Any,
) -> str:
    if output and output.get("plan"):
        return str(output["plan"])
    if app_state is not None:
        return read_plan(app_state) or "No plan found"
    return "No plan found"
