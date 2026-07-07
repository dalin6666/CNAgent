from __future__ import annotations


def extractBashCommentLabel(command: str) -> str | None:
    first_line = command.splitlines()[0].strip() if command.splitlines() else command.strip()
    if not first_line.startswith("#") or first_line.startswith("#!"):
        return None
    label = first_line.lstrip("#").strip()
    return label or None


__all__ = ["extractBashCommentLabel"]
