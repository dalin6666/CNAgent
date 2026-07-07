from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from agent_runtime.schemas import Message


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_system_message(
    content: str,
    *,
    subtype: str | None = None,
    level: str = "info",
    metadata: dict[str, Any] | None = None,
    is_meta: bool = False,
) -> Message:
    payload = {"level": level, **(metadata or {})}
    return Message(
        role="system",
        content=content,
        metadata=payload,
        subtype=subtype,
        is_meta=is_meta,
        timestamp=now_iso(),
        uuid=uuid4().hex,
    )


def create_compact_boundary_message(
    trigger: str,
    pre_tokens: int,
    last_precompact_message_uuid: str | None = None,
    user_context: str | None = None,
    messages_summarized: int | None = None,
) -> Message:
    boundary = create_system_message(
        "Conversation compacted",
        subtype="compact_boundary",
        metadata={
            "compact_metadata": {
                "trigger": trigger,
                "pre_tokens": pre_tokens,
                "user_context": user_context,
                "messages_summarized": messages_summarized,
            }
        },
    )
    if last_precompact_message_uuid:
        boundary.metadata["logical_parent_uuid"] = last_precompact_message_uuid
    return boundary


def create_microcompact_boundary_message(
    trigger: str,
    pre_tokens: int,
    tokens_saved: int,
    compacted_tool_ids: list[str],
    cleared_attachment_uuids: list[str],
) -> Message:
    return create_system_message(
        "Context microcompacted",
        subtype="microcompact_boundary",
        metadata={
            "microcompact_metadata": {
                "trigger": trigger,
                "pre_tokens": pre_tokens,
                "tokens_saved": tokens_saved,
                "compacted_tool_ids": list(compacted_tool_ids),
                "cleared_attachment_uuids": list(cleared_attachment_uuids),
            }
        },
    )


def create_compact_summary_message(
    content: str,
    *,
    recent_messages_preserved: bool = False,
) -> Message:
    metadata = {"compact_summary": True}
    if recent_messages_preserved:
        metadata["recent_messages_preserved"] = True
    return Message(
        role="user",
        content=content,
        metadata=metadata,
        timestamp=now_iso(),
        uuid=uuid4().hex,
    )


def create_attachment_message(
    content: str,
    *,
    attachment_type: str,
    payload: dict[str, Any] | None = None,
) -> Message:
    metadata = {"attachment_type": attachment_type, **(payload or {})}
    return create_system_message(
        content,
        subtype="context_attachment",
        metadata=metadata,
    )


def is_compact_boundary_message(message: Message) -> bool:
    return message.role == "system" and message.subtype == "compact_boundary"


def find_last_compact_boundary_index(messages: list[Message]) -> int:
    for index in range(len(messages) - 1, -1, -1):
        if is_compact_boundary_message(messages[index]):
            return index
    return -1


def get_messages_after_compact_boundary(
    messages: list[Message],
    *,
    include_snipped: bool = False,
) -> list[Message]:
    boundary_index = find_last_compact_boundary_index(messages)
    sliced = messages if boundary_index == -1 else messages[boundary_index:]
    if include_snipped:
        return list(sliced)
    return [
        message
        for message in sliced
        if not message.metadata.get("snipped") and not message.metadata.get("snip_hidden")
    ]


def annotate_boundary_with_preserved_segment(
    boundary: Message,
    anchor_uuid: str,
    messages_to_keep: list[Message] | None,
) -> Message:
    keep = messages_to_keep or []
    if not keep:
        return boundary
    compact_metadata = dict(boundary.metadata.get("compact_metadata", {}))
    compact_metadata["preserved_segment"] = {
        "head_uuid": keep[0].uuid,
        "anchor_uuid": anchor_uuid,
        "tail_uuid": keep[-1].uuid,
    }
    boundary.metadata["compact_metadata"] = compact_metadata
    return boundary
