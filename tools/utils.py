from __future__ import annotations

from typing import Any


def tagMessagesWithToolUseID(messages: list[dict[str, Any]], toolUseID: str | None) -> list[dict[str, Any]]:
    if not toolUseID:
        return list(messages)
    tagged: list[dict[str, Any]] = []
    for message in messages:
        cloned = dict(message)
        if cloned.get('type') == 'user':
            cloned['sourceToolUseID'] = toolUseID
        tagged.append(cloned)
    return tagged


def getToolUseIDFromParentMessage(parentMessage: dict[str, Any], toolName: str) -> str | None:
    content = parentMessage.get('message', {}).get('content', [])
    for block in content:
        if block.get('type') == 'tool_use' and block.get('name') == toolName:
            return block.get('id')
    return None
