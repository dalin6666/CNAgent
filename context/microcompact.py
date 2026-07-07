from __future__ import annotations

from datetime import datetime, timezone

from agent_runtime.runtime.budget import TokenBudgetManager
from agent_runtime.schemas import Message

from .config import MicroCompactConfig
from .messages import create_microcompact_boundary_message
from .storage import TOOL_RESULT_CLEARED_MESSAGE
from .types import (
    ContextSessionState,
    MicroCompactResult,
    MicrocompactInfo,
    PendingCacheEdits,
)


def _message_timestamp(message: Message) -> datetime | None:
    try:
        return datetime.fromisoformat(message.timestamp)
    except Exception:  # noqa: BLE001
        return None


class MicroCompactor:
    def __init__(self, budget_manager: TokenBudgetManager | None = None) -> None:
        self.budget_manager = budget_manager or TokenBudgetManager()

    def estimate_message_tokens(self, messages: list[Message]) -> int:
        return self.budget_manager.estimate_prompt_tokens(messages)

    def microcompact_messages(
        self,
        messages: list[Message],
        state: ContextSessionState,
        *,
        config: MicroCompactConfig,
        query_source: str = "main",
    ) -> MicroCompactResult:
        if not config.enabled:
            return MicroCompactResult(messages=list(messages))

        time_based = self._maybe_time_based_microcompact(
            messages,
            state,
            config=config,
            query_source=query_source,
        )
        if time_based is not None:
            state.warning_suppressed = True
            return time_based

        cached = self._maybe_cached_microcompact(
            messages,
            state,
            config=config,
            query_source=query_source,
        )
        if cached is not None:
            state.warning_suppressed = True
            return cached

        state.warning_suppressed = False
        return MicroCompactResult(messages=list(messages))

    def mark_tools_sent_to_api_state(self, state: ContextSessionState) -> None:
        state.pending_cache_edits = None

    def reset_microcompact_state(self, state: ContextSessionState) -> None:
        state.registered_tool_order.clear()
        state.deleted_tool_ids.clear()
        state.pending_cache_edits = None
        state.pinned_cache_edits.clear()

    def evaluate_time_based_trigger(
        self,
        messages: list[Message],
        state: ContextSessionState,
        *,
        config: MicroCompactConfig,
        query_source: str,
    ) -> dict[str, float] | None:
        if not config.time_based_enabled:
            return None
        if query_source.startswith("agent:"):
            return None
        last_assistant = next(
            (message for message in reversed(messages) if message.role == "assistant"),
            None,
        )
        timestamp = _message_timestamp(last_assistant) if last_assistant else None
        if timestamp is None and state.last_assistant_timestamp:
            try:
                timestamp = datetime.fromisoformat(state.last_assistant_timestamp)
            except Exception:  # noqa: BLE001
                timestamp = None
        if timestamp is None:
            return None
        gap_minutes = (
            datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)
        ).total_seconds() / 60.0
        if gap_minutes < config.time_gap_threshold_minutes:
            return None
        return {
            "gap_minutes": gap_minutes,
            "keep_recent": float(max(1, config.time_based_keep_recent)),
        }

    def _maybe_time_based_microcompact(
        self,
        messages: list[Message],
        state: ContextSessionState,
        *,
        config: MicroCompactConfig,
        query_source: str,
    ) -> MicroCompactResult | None:
        trigger = self.evaluate_time_based_trigger(
            messages,
            state,
            config=config,
            query_source=query_source,
        )
        if trigger is None:
            return None

        compactable = self._collect_compactable_tool_messages(messages, config)
        keep_recent = int(trigger["keep_recent"])
        keep_ids = {
            tool_id for tool_id, _ in compactable[-keep_recent:]
        }
        clear_ids = {
            tool_id for tool_id, _ in compactable if tool_id not in keep_ids
        }
        if not clear_ids:
            return None

        tokens_saved = 0
        result: list[Message] = []
        cleared_ids: list[str] = []
        for message in messages:
            tool_id = message.tool_call_id or message.uuid
            if message.role == "tool" and tool_id in clear_ids and message.content != TOOL_RESULT_CLEARED_MESSAGE:
                tokens_saved += self.estimate_message_tokens([message])
                cleared_ids.append(tool_id)
                result.append(
                    Message(
                        role=message.role,
                        content=TOOL_RESULT_CLEARED_MESSAGE,
                        name=message.name,
                        tool_call_id=message.tool_call_id,
                        metadata={**message.metadata, "microcompacted": True},
                        folded=message.folded,
                        timestamp=message.timestamp,
                        uuid=message.uuid,
                        subtype=message.subtype,
                        is_meta=message.is_meta,
                    )
                )
            else:
                result.append(message)

        if tokens_saved <= 0:
            return None

        boundary = create_microcompact_boundary_message(
            "auto",
            0,
            tokens_saved,
            cleared_ids,
            [],
        )
        info = MicrocompactInfo(
            compacted_tool_ids=cleared_ids,
            cleared_attachment_uuids=[],
            tokens_saved=tokens_saved,
        )
        notes = [
            "time-based microcompact cleared older tool results after a long assistant gap"
        ]
        self.reset_microcompact_state(state)
        return MicroCompactResult(
            messages=result,
            boundary_message=boundary,
            compaction_info=info,
            notes=notes,
        )

    def _maybe_cached_microcompact(
        self,
        messages: list[Message],
        state: ContextSessionState,
        *,
        config: MicroCompactConfig,
        query_source: str,
    ) -> MicroCompactResult | None:
        if not config.cached_enabled:
            return None
        if query_source.startswith("agent:"):
            return None

        compactable = self._collect_compactable_tool_messages(messages, config)
        for tool_id, _message in compactable:
            if tool_id not in state.registered_tool_order:
                state.registered_tool_order.append(tool_id)

        active_ids = [
            tool_id
            for tool_id in state.registered_tool_order
            if tool_id not in state.deleted_tool_ids
        ]
        if len(active_ids) <= config.cached_trigger_threshold:
            return None

        delete_count = max(len(active_ids) - config.cached_keep_recent, 0)
        to_delete = active_ids[:delete_count]
        if not to_delete:
            return None

        state.deleted_tool_ids.update(to_delete)
        state.pending_cache_edits = PendingCacheEdits(
            trigger="auto",
            deleted_tool_ids=list(to_delete),
            baseline_deleted_tokens=0,
        )

        local_projection = []
        tokens_saved = 0
        for message in messages:
            tool_id = message.tool_call_id or message.uuid
            if message.role == "tool" and tool_id in state.deleted_tool_ids:
                if message.content != TOOL_RESULT_CLEARED_MESSAGE:
                    tokens_saved += self.estimate_message_tokens([message])
                local_projection.append(
                    Message(
                        role=message.role,
                        content=TOOL_RESULT_CLEARED_MESSAGE,
                        name=message.name,
                        tool_call_id=message.tool_call_id,
                        metadata={**message.metadata, "cached_microcompacted": True},
                        folded=message.folded,
                        timestamp=message.timestamp,
                        uuid=message.uuid,
                        subtype=message.subtype,
                        is_meta=message.is_meta,
                    )
                )
            else:
                local_projection.append(message)

        boundary = create_microcompact_boundary_message(
            "auto",
            0,
            tokens_saved,
            list(to_delete),
            [],
        )
        info = MicrocompactInfo(
            pending_cache_edits=state.pending_cache_edits,
            compacted_tool_ids=list(to_delete),
            tokens_saved=tokens_saved,
        )
        notes = [
            "cached microcompact projected prompt-cache-safe tool result deletions"
        ]
        return MicroCompactResult(
            messages=local_projection,
            boundary_message=boundary,
            compaction_info=info,
            notes=notes,
        )

    def _collect_compactable_tool_messages(
        self,
        messages: list[Message],
        config: MicroCompactConfig,
    ) -> list[tuple[str, Message]]:
        allowed = set(config.compactable_tool_names)
        result: list[tuple[str, Message]] = []
        for message in messages:
            if message.role != "tool":
                continue
            tool_name = message.name or ""
            if tool_name not in allowed:
                payload = _safe_tool_payload(message)
                tool_name = str(payload.get("tool", "")) if payload else tool_name
            if tool_name not in allowed:
                continue
            result.append((message.tool_call_id or message.uuid, message))
        return result


def _safe_tool_payload(message: Message) -> dict[str, object] | None:
    try:
        import json

        payload = json.loads(message.content)
    except Exception:  # noqa: BLE001
        return None
    return payload if isinstance(payload, dict) else None
