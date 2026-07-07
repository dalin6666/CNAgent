from __future__ import annotations

from ..config import RuntimeConfig
from ..schemas import BudgetStatus, Message


def estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def estimate_message_tokens(message: Message) -> int:
    return estimate_text_tokens(message.content) + 6


class TokenBudgetManager:
    def estimate_prompt_tokens(self, messages: list[Message]) -> int:
        return sum(estimate_message_tokens(message) for message in messages)

    def evaluate(
        self,
        messages: list[Message],
        config: RuntimeConfig,
        *,
        provider_context_limit: int | None = None,
    ) -> BudgetStatus:
        prompt_tokens = self.estimate_prompt_tokens(messages)
        hard_limit = provider_context_limit or config.context_window_tokens
        available_input_tokens = max(hard_limit - config.reserved_output_tokens, 0)
        overflow = max(prompt_tokens - available_input_tokens, 0)
        return BudgetStatus(
            estimated_prompt_tokens=prompt_tokens,
            available_input_tokens=available_input_tokens,
            needs_compression=overflow > 0,
            overflow_tokens=overflow,
        )
