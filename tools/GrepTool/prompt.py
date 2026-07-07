from __future__ import annotations

from ..AgentTool.constants import AGENT_TOOL_NAME
from ..BashTool.toolName import BASH_TOOL_NAME

GREP_TOOL_NAME = "Grep"


def getDescription() -> str:
    return (
        "A powerful search tool built on ripgrep\n\n"
        "Usage:\n"
        f"- ALWAYS use {GREP_TOOL_NAME} for search tasks. NEVER invoke `grep` or `rg` "
        f"as a {BASH_TOOL_NAME} command. The {GREP_TOOL_NAME} tool has been "
        "optimized for correct permissions and access.\n"
        '- Supports full regex syntax (for example "log.*Error", "function\\s+\\w+")\n'
        '- Filter files with glob parameter (for example "*.js", "**/*.tsx") or '
        'type parameter (for example "js", "py", "rust")\n'
        '- Output modes: "content" shows matching lines, "files_with_matches" shows '
        'only file paths (default), "count" shows match counts\n'
        f"- Use {AGENT_TOOL_NAME} tool for open-ended searches requiring multiple rounds\n"
        "- Pattern syntax: Uses ripgrep (not grep); literal braces need escaping "
        "(use `interface\\{\\}` to find `interface{}` in Go code)\n"
        "- Multiline matching: By default patterns match within single lines only. "
        "For cross-line patterns like `struct \\{[\\s\\S]*?field`, use `multiline: true`\n"
    )


__all__ = ["GREP_TOOL_NAME", "getDescription"]
