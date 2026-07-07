from __future__ import annotations

from typing import Any


def format_bash_tool_result(output: dict[str, Any] | None = None) -> str:
    output = output or {}
    stdout = str(output.get("stdout", "")).strip()
    stderr = str(output.get("stderr", "")).strip()
    if stdout and stderr:
        return f"{stdout}\n{stderr}"
    return stdout or stderr or "Done"


__all__ = ["format_bash_tool_result"]
