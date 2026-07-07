from __future__ import annotations

DEFAULT_TIMEOUT_MS = 30_000
MAX_TIMEOUT_MS = 10 * 60 * 1000


def getDefaultTimeoutMs() -> int:
    return DEFAULT_TIMEOUT_MS


def getMaxTimeoutMs() -> int:
    return MAX_TIMEOUT_MS


def getSimplePrompt() -> str:
    return """
Executes a given bash command and returns its output.

The working directory persists between commands, but shell state does not. Prefer dedicated file tools for searching, reading, and editing when they can accomplish the task more clearly.

Instructions:
- Prefer read/search commands over ad-hoc shell scripts when possible.
- Use absolute paths when it helps keep the working directory stable.
- Quote paths that contain spaces with double quotes.
- Use `run_in_background` for long-running commands when you do not need the result immediately.
- Avoid unnecessary `sleep` commands; if you need a short delay, keep it brief.
- Default timeout is 30000ms and the maximum timeout is 600000ms.
""".strip()


__all__ = ["getDefaultTimeoutMs", "getMaxTimeoutMs", "getSimplePrompt"]
