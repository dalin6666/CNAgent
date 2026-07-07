from __future__ import annotations

import re
import shlex
from typing import Any


_DANGEROUS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"`[^`]*`"), "Backtick command substitution requires approval"),
    (re.compile(r"\$\("), "Command substitution requires approval"),
    (re.compile(r"(?:^|[^<])<\("), "Process substitution requires approval"),
    (re.compile(r">\("), "Process substitution requires approval"),
]


def hasSafeHeredocSubstitution(command: str) -> bool:
    return bool(re.search(r"<<[-~]?\s*(['\"]).+?\1", command))


def stripSafeHeredocSubstitutions(command: str) -> str | None:
    if "<<" not in command:
        return command
    if not hasSafeHeredocSubstitution(command):
        return None
    return re.sub(r"<<[-~]?\s*(['\"]).+?\1", "<<HEREDOC", command)


def bashCommandIsSafe_DEPRECATED(command: str) -> dict[str, Any]:
    stripped = command.strip()
    if not stripped:
        return {"behavior": "passthrough", "message": "Empty command"}
    try:
        shlex.split(stripped, posix=True)
    except ValueError as exc:
        return {
            "behavior": "ask",
            "message": f"Malformed shell syntax requires approval: {exc}",
            "isBashSecurityCheckForMisparsing": True,
        }
    for pattern, message in _DANGEROUS_PATTERNS:
        if pattern.search(stripped):
            return {
                "behavior": "ask",
                "message": message,
                "isBashSecurityCheckForMisparsing": False,
            }
    return {"behavior": "passthrough", "message": "No shell security issues detected"}


async def bashCommandIsSafeAsync_DEPRECATED(command: str, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
    return bashCommandIsSafe_DEPRECATED(command)


__all__ = [
    "bashCommandIsSafeAsync_DEPRECATED",
    "bashCommandIsSafe_DEPRECATED",
    "hasSafeHeredocSubstitution",
    "stripSafeHeredocSubstitutions",
]
