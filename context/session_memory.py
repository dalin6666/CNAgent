from __future__ import annotations

from agent_runtime.runtime.budget import TokenBudgetManager
from agent_runtime.schemas import Message

from .config import SessionMemoryCompactConfig
from .messages import (
    annotate_boundary_with_preserved_segment,
    create_compact_boundary_message,
    create_compact_summary_message,
)
from .prompt import get_compact_user_summary_message
from .types import CompactionResult, ContextSessionState


def has_text_blocks(message: Message) -> bool:
    return message.role in {"user", "assistant", "system"} and bool(message.content.strip())


def get_tool_result_ids(message: Message) -> list[str]:
    if message.role != "tool":
        return []
    return [message.tool_call_id or message.uuid]


def has_tool_use_with_ids(message: Message, tool_use_ids: set[str]) -> bool:
    if message.role != "assistant":
        return False
    tool_calls = message.metadata.get("tool_calls", [])
    for tool_call in tool_calls:
        if isinstance(tool_call, dict) and str(tool_call.get("id", "")) in tool_use_ids:
            return True
    return False


class SessionMemoryCompactor:
    def __init__(self, budget_manager: TokenBudgetManager | None = None) -> None:
        self.budget_manager = budget_manager or TokenBudgetManager()

    def adjust_index_to_preserve_api_invariants(
        self,
        messages: list[Message],
        start_index: int,
    ) -> int:
        if start_index <= 0 or start_index >= len(messages):
            return start_index

        adjusted = start_index
        all_tool_result_ids: list[str] = []
        for message in messages[start_index:]:
            all_tool_result_ids.extend(get_tool_result_ids(message))

        if all_tool_result_ids:
            needed_ids = set(all_tool_result_ids)
            for message in messages[adjusted:]:
                if message.role == "assistant":
                    for tool_call in message.metadata.get("tool_calls", []):
                        if isinstance(tool_call, dict):
                            needed_ids.discard(str(tool_call.get("id", "")))

            for index in range(adjusted - 1, -1, -1):
                if not needed_ids:
                    break
                message = messages[index]
                if has_tool_use_with_ids(message, needed_ids):
                    adjusted = index
                    for tool_call in message.metadata.get("tool_calls", []):
                        if isinstance(tool_call, dict):
                            needed_ids.discard(str(tool_call.get("id", "")))

        return adjusted

    def calculate_messages_to_keep_index(
        self,
        messages: list[Message],
        last_summarized_index: int,
        *,
        config: SessionMemoryCompactConfig,
    ) -> int:
        if not messages:
            return 0

        start_index = last_summarized_index + 1 if last_summarized_index >= 0 else len(messages)
        total_tokens = sum(
            self.budget_manager.estimate_prompt_tokens([message])
            for message in messages[start_index:]
        )
        text_message_count = sum(1 for message in messages[start_index:] if has_text_blocks(message))

        if total_tokens >= config.max_tokens:
            return self.adjust_index_to_preserve_api_invariants(messages, start_index)
        if total_tokens >= config.min_tokens and text_message_count >= config.min_text_messages:
            return self.adjust_index_to_preserve_api_invariants(messages, start_index)

        for index in range(start_index - 1, -1, -1):
            message = messages[index]
            total_tokens += self.budget_manager.estimate_prompt_tokens([message])
            if has_text_blocks(message):
                text_message_count += 1
            start_index = index
            if total_tokens >= config.max_tokens:
                break
            if total_tokens >= config.min_tokens and text_message_count >= config.min_text_messages:
                break

        return self.adjust_index_to_preserve_api_invariants(messages, start_index)

    def try_session_memory_compaction(
        self,
        session_id: str,
        messages: list[Message],
        state: ContextSessionState,
        *,
        config: SessionMemoryCompactConfig,
    ) -> CompactionResult | None:
        if not config.enabled or not state.session_memory_sections:
            return None

        session_memory = "\n\n".join(state.session_memory_sections[-6:])
        if not session_memory.strip():
            return None

        if state.last_summarized_message_uuid:
            last_index = next(
                (
                    index
                    for index, message in enumerate(messages)
                    if message.uuid == state.last_summarized_message_uuid
                ),
                -1,
            )
        else:
            last_index = -1

        keep_index = self.calculate_messages_to_keep_index(
            messages,
            last_index,
            config=config,
        )
        messages_to_keep = list(messages[keep_index:])
        boundary = create_compact_boundary_message(
            "auto",
            self.budget_manager.estimate_prompt_tokens(messages),
            messages[-1].uuid if messages else None,
            messages_summarized=max(keep_index, 0),
        )
        summary_content = get_compact_user_summary_message(
            session_memory,
            suppress_follow_up_questions=True,
            transcript_path=f"{session_id}:session-memory",
            recent_messages_preserved=True,
        )
        summary_message = create_compact_summary_message(
            summary_content,
            recent_messages_preserved=True,
        )
        boundary = annotate_boundary_with_preserved_segment(
            boundary,
            summary_message.uuid,
            messages_to_keep,
        )
        return CompactionResult(
            boundary_marker=boundary,
            summary_messages=[summary_message],
            attachments=[],
            hook_results=[],
            messages_to_keep=messages_to_keep,
            pre_compact_token_count=self.budget_manager.estimate_prompt_tokens(messages),
            post_compact_token_count=self.budget_manager.estimate_prompt_tokens([summary_message]),
            true_post_compact_token_count=self.budget_manager.estimate_prompt_tokens(
                [summary_message, *messages_to_keep]
            ),
            trigger="auto",
        )
