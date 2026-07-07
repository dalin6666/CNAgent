from __future__ import annotations

from agent_runtime.config import RuntimeConfig
from agent_runtime.runtime.budget import TokenBudgetManager
from agent_runtime.schemas import Message

from .compaction import ConversationCompactor
from .types import CompactionResult, ContextSessionState

MEDIA_ERROR_FRAGMENTS = (
    "image too large",
    "media too large",
    "document too large",
    "request entity too large",
    "payload too large",
)


class ReactiveCompactor:
    def __init__(
        self,
        *,
        budget_manager: TokenBudgetManager | None = None,
        conversation_compactor: ConversationCompactor,
    ) -> None:
        self.budget_manager = budget_manager or TokenBudgetManager()
        self.conversation_compactor = conversation_compactor

    def is_prompt_too_long_error(self, error: Exception) -> bool:
        message = str(error).lower()
        return any(
            fragment in message
            for fragment in (
                "context length",
                "prompt too long",
                "too many tokens",
                "maximum context length",
                "max context",
            )
        )

    def is_media_size_error(self, error: Exception) -> bool:
        message = str(error).lower()
        return any(fragment in message for fragment in MEDIA_ERROR_FRAGMENTS)

    def try_reactive_compact(
        self,
        session_id: str,
        messages: list[Message],
        state: ContextSessionState,
        runtime_config: RuntimeConfig,
        *,
        error: Exception,
        has_attempted: bool = False,
    ) -> tuple[CompactionResult | None, list[str]]:
        notes: list[str] = []
        if not runtime_config.context_config.reactive.enabled or has_attempted:
            return None, notes

        recoverable_ptl = self.is_prompt_too_long_error(error)
        recoverable_media = self.is_media_size_error(error)
        if not recoverable_ptl and not recoverable_media:
            return None, notes

        working = list(messages)
        if recoverable_media and runtime_config.context_config.reactive.strip_attachment_messages_first:
            stripped = self.conversation_compactor.strip_attachment_messages(working)
            if len(stripped) != len(working):
                working = stripped
                notes.append("reactive compact stripped attachment messages before retry")

        if recoverable_ptl and runtime_config.context_config.reactive.retry_with_truncated_head:
            truncated = self.conversation_compactor.truncate_head_for_ptl_retry(
                working,
                max_messages=runtime_config.context_config.reactive.max_truncated_head_messages,
            )
            if len(truncated) != len(working):
                working = truncated
                notes.append("reactive compact truncated the oldest head messages before summarizing")

        result = self.conversation_compactor.compact_conversation(
            session_id,
            working,
            state,
            runtime_config.context_config,
            trigger="reactive",
            preserve_tail_messages=runtime_config.context_config.auto.partial_summary_keep_tail_messages,
        )
        notes.append("reactive compact produced a recovery summary after provider rejection")
        return result, notes
