from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from agent_runtime.schemas import Message

from .config import ToolResultBudgetConfig
from .storage import (
    PERSISTED_OUTPUT_TAG,
    TOOL_RESULT_CLEARED_MESSAGE,
    ContextStorage,
)
from .types import ContentReplacementRecord, ContextSessionState


def _message_content_size(message: Message) -> int:
    return len(message.content)


def _is_already_compacted(message: Message) -> bool:
    return message.content.startswith(PERSISTED_OUTPUT_TAG) or message.content == TOOL_RESULT_CLEARED_MESSAGE


def _tool_use_id(message: Message) -> str:
    return message.tool_call_id or message.uuid


def _replace_message_content(message: Message, replacement: str) -> Message:
    return Message(
        role=message.role,
        content=replacement,
        name=message.name,
        tool_call_id=message.tool_call_id,
        metadata={**message.metadata, "tool_result_replaced": True},
        folded=message.folded,
        timestamp=message.timestamp,
        uuid=message.uuid,
        subtype=message.subtype,
        is_meta=message.is_meta,
    )


@dataclass(slots=True)
class ToolResultCandidate:
    message_index: int
    tool_use_id: str
    tool_name: str
    size: int
    content: str


def build_tool_name_map(messages: list[Message]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for message in messages:
        if message.role != "assistant":
            continue
        for tool_call in message.metadata.get("tool_calls", []):
            if isinstance(tool_call, dict) and tool_call.get("id"):
                mapping[str(tool_call["id"])] = str(tool_call.get("name", "tool"))
    for message in messages:
        if message.role == "tool" and message.tool_call_id and message.name:
            mapping.setdefault(message.tool_call_id, message.name)
        elif message.role == "tool" and message.tool_call_id:
            payload = _safe_json_loads(message.content)
            if isinstance(payload, dict) and payload.get("tool"):
                mapping.setdefault(message.tool_call_id, str(payload["tool"]))
    return mapping


def _safe_json_loads(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return None


def collect_candidates_by_group(messages: list[Message]) -> list[list[ToolResultCandidate]]:
    groups: list[list[ToolResultCandidate]] = []
    current: list[ToolResultCandidate] = []
    tool_name_map = build_tool_name_map(messages)

    def flush() -> None:
        nonlocal current
        if current:
            groups.append(current)
        current = []

    for index, message in enumerate(messages):
        if message.role == "tool" and not _is_already_compacted(message) and message.content.strip():
            current.append(
                ToolResultCandidate(
                    message_index=index,
                    tool_use_id=_tool_use_id(message),
                    tool_name=tool_name_map.get(_tool_use_id(message), message.name or "tool"),
                    size=_message_content_size(message),
                    content=message.content,
                )
            )
            continue
        flush()
    flush()
    return groups


def _select_fresh_to_replace(
    fresh: list[ToolResultCandidate],
    frozen_size: int,
    limit: int,
) -> list[ToolResultCandidate]:
    selected: list[ToolResultCandidate] = []
    remaining = frozen_size + sum(item.size for item in fresh)
    for candidate in sorted(fresh, key=lambda item: item.size, reverse=True):
        if remaining <= limit:
            break
        selected.append(candidate)
        remaining -= candidate.size
    return selected


def enforce_tool_result_budget(
    messages: list[Message],
    session_id: str,
    state: ContextSessionState,
    storage: ContextStorage,
    config: ToolResultBudgetConfig,
) -> tuple[list[Message], list[ContentReplacementRecord], list[str]]:
    if not config.enabled:
        return messages, [], []

    groups = collect_candidates_by_group(messages)
    if not groups:
        return messages, [], []

    replacement_map: dict[int, str] = {}
    new_records: list[ContentReplacementRecord] = []
    notes: list[str] = []

    for group in groups:
        must_reapply = [
            item
            for item in group
            if item.tool_use_id in state.tool_result_replacements
        ]
        frozen = [
            item
            for item in group
            if item.tool_use_id in state.seen_tool_result_ids
            and item.tool_use_id not in state.tool_result_replacements
        ]
        fresh = [
            item
            for item in group
            if item.tool_use_id not in state.seen_tool_result_ids
            and item.tool_use_id not in state.tool_result_replacements
            and item.tool_name not in config.skip_persist_tool_names
        ]
        skipped = [
            item
            for item in group
            if item.tool_use_id not in state.seen_tool_result_ids
            and item.tool_name in config.skip_persist_tool_names
        ]

        for item in must_reapply:
            replacement_map[item.message_index] = state.tool_result_replacements[item.tool_use_id]
            state.seen_tool_result_ids.add(item.tool_use_id)
        for item in skipped:
            state.seen_tool_result_ids.add(item.tool_use_id)

        frozen_size = sum(item.size for item in frozen)
        selected = _select_fresh_to_replace(
            fresh,
            frozen_size=frozen_size,
            limit=config.per_message_char_limit,
        )
        selected_ids = {item.tool_use_id for item in selected}

        for item in group:
            if item.tool_use_id not in selected_ids:
                state.seen_tool_result_ids.add(item.tool_use_id)

        for item in selected:
            persisted = storage.persist_tool_result(
                session_id,
                item.tool_use_id,
                item.content,
            )
            replacement = storage.build_large_tool_result_message(persisted)
            replacement_map[item.message_index] = replacement
            state.tool_result_replacements[item.tool_use_id] = replacement
            state.seen_tool_result_ids.add(item.tool_use_id)
            new_records.append(
                ContentReplacementRecord(
                    kind="tool-result",
                    tool_use_id=item.tool_use_id,
                    replacement=replacement,
                )
            )

    if not replacement_map:
        return messages, [], []

    replaced_messages = list(messages)
    replaced_count = 0
    for index, replacement in replacement_map.items():
        replaced_messages[index] = _replace_message_content(messages[index], replacement)
        replaced_count += 1

    notes.append(
        f"tool result budget persisted or replayed {replaced_count} large tool result message(s)"
    )
    return replaced_messages, new_records, notes


def reconstruct_content_replacement_state(
    messages: list[Message],
    records: list[ContentReplacementRecord],  # 保存的的内容替换记录，将较长的tool result进行简化替换
    state: ContextSessionState | None = None,
) -> ContextSessionState:
    next_state = state or ContextSessionState()
    candidates = collect_candidates_by_group(messages)
    candidate_ids = {candidate.tool_use_id for group in candidates for candidate in group}
    next_state.seen_tool_result_ids.update(candidate_ids)
    for record in records:
        if record.tool_use_id in candidate_ids:
            next_state.tool_result_replacements[record.tool_use_id] = record.replacement
    return next_state
