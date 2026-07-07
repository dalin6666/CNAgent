from __future__ import annotations

from agent_runtime.config import RuntimeConfig
from agent_runtime.runtime.budget import TokenBudgetManager
from agent_runtime.schemas import Message

from .compaction import ConversationCompactor
from .config import ContextConfig
from .session_memory import SessionMemoryCompactor
from .types import CompactionResult, ContextSessionState, TokenWarningState


class AutoCompactor:
    def __init__(
        self,
        *,
        budget_manager: TokenBudgetManager | None = None,
        conversation_compactor: ConversationCompactor,
        session_memory_compactor: SessionMemoryCompactor,
    ) -> None:
        self.budget_manager = budget_manager or TokenBudgetManager()
        self.conversation_compactor = conversation_compactor
        self.session_memory_compactor = session_memory_compactor

    def get_effective_context_window_size(
        self,
        runtime_config: RuntimeConfig,
        *,
        provider_context_limit: int | None = None,
    ) -> int:
        hard_limit = provider_context_limit or runtime_config.context_window_tokens
        return max(hard_limit - runtime_config.reserved_output_tokens, 0)

    def get_auto_compact_threshold(
        self,
        runtime_config: RuntimeConfig,
        *,
        provider_context_limit: int | None = None,
    ) -> int:
        effective = self.get_effective_context_window_size(
            runtime_config,
            provider_context_limit=provider_context_limit,
        )
        return max(
            effective - runtime_config.context_config.auto.autocompact_buffer_tokens,
            0,
        )

    def calculate_token_warning_state(
        self,
        token_usage: int,
        runtime_config: RuntimeConfig,
        *,
        provider_context_limit: int | None = None,
    ) -> TokenWarningState:
        auto_threshold = self.get_auto_compact_threshold(
            runtime_config,
            provider_context_limit=provider_context_limit,
        )
        effective = self.get_effective_context_window_size(
            runtime_config,
            provider_context_limit=provider_context_limit,
        )
        threshold = auto_threshold if runtime_config.context_config.auto.enabled else effective
        percent_left = max(0, round(((threshold - token_usage) / max(threshold, 1)) * 100))
        warning_threshold = max(
            threshold - runtime_config.context_config.auto.warning_buffer_tokens,
            0,
        )
        error_threshold = max(
            threshold - runtime_config.context_config.auto.error_buffer_tokens,
            0,
        )
        blocking_limit = max(
            effective - runtime_config.context_config.auto.manual_compact_buffer_tokens,
            0,
        )
        return TokenWarningState(
            percent_left=percent_left,
            is_above_warning_threshold=token_usage >= warning_threshold,
            is_above_error_threshold=token_usage >= error_threshold,
            is_above_autocompact_threshold=token_usage >= auto_threshold,
            is_at_blocking_limit=token_usage >= blocking_limit,
        )

    def should_auto_compact(
        self,
        messages: list[Message],
        runtime_config: RuntimeConfig,
        *,
        provider_context_limit: int | None = None,
        query_source: str = "main",
        snip_tokens_freed: int = 0,
    ) -> bool:
        if not runtime_config.context_config.auto.enabled:
            return False
        if query_source in {"compact", "session_memory"}:
            return False
        token_usage = self.budget_manager.estimate_prompt_tokens(messages) - snip_tokens_freed
        state = self.calculate_token_warning_state(
            token_usage,
            runtime_config,
            provider_context_limit=provider_context_limit,
        )
        return state.is_above_autocompact_threshold

    def auto_compact_if_needed(
        self,
        session_id: str,
        messages: list[Message],
        state: ContextSessionState,
        runtime_config: RuntimeConfig,
        *,
        provider_context_limit: int | None = None,
        query_source: str = "main",
        snip_tokens_freed: int = 0,
    ) -> tuple[CompactionResult | None, list[str]]:
        notes: list[str] = []
        if not self.should_auto_compact(
            messages,
            runtime_config,
            provider_context_limit=provider_context_limit,
            query_source=query_source,
            snip_tokens_freed=snip_tokens_freed,
        ):
            return None, notes

        max_failures = runtime_config.context_config.auto.max_consecutive_failures
        if state.consecutive_autocompact_failures >= max_failures:
            notes.append(
                "autocompact circuit breaker skipped compaction after repeated failures"
            )
            return None, notes

        session_memory_result = self.session_memory_compactor.try_session_memory_compaction(
            session_id,
            messages,
            state,
            config=runtime_config.context_config.session_memory,
        )
        if session_memory_result is not None:
            state.consecutive_autocompact_failures = 0
            notes.append("session memory compaction provided the next compact summary")
            return session_memory_result, notes

        try:
            result = self.conversation_compactor.compact_conversation(
                session_id,
                messages,
                state,
                runtime_config.context_config,
                trigger="auto",
            )
        except Exception as exc:  # noqa: BLE001
            state.consecutive_autocompact_failures += 1
            notes.append(f"autocompact failed: {exc}")
            return None, notes

        state.consecutive_autocompact_failures = 0
        state.post_compaction_pending = True
        notes.append("autocompact summarized older context and restored recent working state")
        return result, notes
