from __future__ import annotations

from .constants import REPL_ONLY_TOOLS


def get_primitive_tools() -> list[str]:
    return list(REPL_ONLY_TOOLS)
