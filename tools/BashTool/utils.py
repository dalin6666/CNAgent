from __future__ import annotations

import re
from typing import Any


def stripEmptyLines(content: str) -> str:
    lines = content.split("\n")
    start = 0
    while start < len(lines) and lines[start].strip() == "":
        start += 1
    end = len(lines) - 1
    while end >= start and lines[end].strip() == "":
        end -= 1
    if start > end:
        return ""
    return "\n".join(lines[start : end + 1])


def isImageOutput(content: str) -> bool:
    return bool(re.match(r"^data:image/[a-z0-9.+_-]+;base64,", content.strip(), flags=re.IGNORECASE))


def parseDataUri(value: str) -> dict[str, str] | None:
    match = re.match(r"^data:([^;]+);base64,(.+)$", value.strip(), flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return {"mediaType": match.group(1), "data": match.group(2)}


def buildImageToolResult(stdout: str, toolUseID: str) -> dict[str, Any] | None:
    parsed = parseDataUri(stdout)
    if parsed is None:
        return None
    return {
        "tool_use_id": toolUseID,
        "type": "tool_result",
        "content": [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": parsed["mediaType"],
                    "data": parsed["data"],
                },
            }
        ],
    }


def resizeShellImageOutput(
    stdout: str,
    _outputFilePath: str | None = None,
    _outputFileSize: int | None = None,
) -> str | None:
    return stdout if parseDataUri(stdout) is not None else None


def formatOutput(content: str, maxOutputLength: int = 12_000) -> dict[str, Any]:
    if isImageOutput(content):
        return {"totalLines": 1, "truncatedContent": content, "isImage": True}
    total_lines = content.count("\n") + 1 if content else 0
    if len(content) <= maxOutputLength:
        return {"totalLines": total_lines, "truncatedContent": content, "isImage": False}
    truncated = content[:maxOutputLength]
    remaining_lines = content[maxOutputLength:].count("\n") + 1
    return {
        "totalLines": total_lines,
        "truncatedContent": f"{truncated}\n\n... [{remaining_lines} lines truncated] ...",
        "isImage": False,
    }


def stdErrAppendShellResetMessage(stderr: str, cwd: str | None = None) -> str:
    suffix = f"Shell cwd was reset to {cwd}" if cwd else "Shell cwd was reset"
    return f"{stderr.strip()}\n{suffix}".strip()


def resetCwdIfOutsideProject(_toolPermissionContext: dict[str, Any] | None = None) -> bool:
    return False


def createContentSummary(content: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    text_count = 0
    image_count = 0
    for block in content:
        if block.get("type") == "image":
            image_count += 1
        elif block.get("type") == "text":
            text_count += 1
            text = str(block.get("text", ""))
            parts.append(text[:200] + ("..." if len(text) > 200 else ""))
    summary: list[str] = []
    if image_count:
        summary.append(f"[{image_count} image{'s' if image_count != 1 else ''}]")
    if text_count:
        summary.append(f"[{text_count} text block{'s' if text_count != 1 else ''}]")
    return "MCP Result: " + ", ".join(summary) + (f"\n\n{chr(10).join(parts)}" if parts else "")


__all__ = [
    "buildImageToolResult",
    "createContentSummary",
    "formatOutput",
    "isImageOutput",
    "parseDataUri",
    "resetCwdIfOutsideProject",
    "resizeShellImageOutput",
    "stdErrAppendShellResetMessage",
    "stripEmptyLines",
]
