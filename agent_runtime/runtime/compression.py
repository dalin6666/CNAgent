from __future__ import annotations

from context.manager import ContextManager

from ..config import RuntimeConfig
from ..schemas import Message, SessionState
from .budget import TokenBudgetManager


class ContextCompressor:
    def __init__(
        self,
        budget_manager: TokenBudgetManager | None = None,
        *,
        context_manager: ContextManager | None = None,
        log_dir: str = ".agent_runtime_logs",
    ) -> None:
        self.budget_manager = budget_manager or TokenBudgetManager()
        self.context_manager = context_manager or ContextManager(
            budget_manager=self.budget_manager,
            log_dir=log_dir,
        )

    def fit_messages(
        self,
        messages: list[Message],
        config: RuntimeConfig,
        *,
        session: SessionState | None = None,
        provider_context_limit: int | None = None,
        compression_level: int = 0,
        query_source: str = "main",
    ) -> tuple[list[Message], list[str]]:
        if session is not None and config.context_config.enabled:
            return self.context_manager.prepare_messages(
                session=session,
                runtime_config=config,
                provider_context_limit=provider_context_limit,
                compression_level=compression_level,
                query_source=query_source,
            )

        folded = [self._fold_message(message) for message in messages]
        status = self.budget_manager.evaluate(
            folded,
            config,
            provider_context_limit=provider_context_limit,
        )
        if not status.needs_compression:
            return folded, []

        notes: list[str] = []
        tail_count = max(config.compression_tail_messages - compression_level, 3)
        summary_count = max(config.compression_summary_messages + compression_level, 4)
        tail = folded[-tail_count:]
        older = folded[:-tail_count]

        if older:
            summary_lines = [
                f"{message.role}: {message.short(160)}"
                for message in older[-summary_count:]
            ]
            summary_message = Message(
                role="system",
                content="Compressed conversation summary:\n" + "\n".join(summary_lines),
                metadata={"compressed": True, "compression_level": compression_level},
                folded=True,
            )
            folded = [summary_message, *tail]
            notes.append("older messages were compressed into a summary")
        else:
            folded = tail

        status = self.budget_manager.evaluate(
            folded,
            config,
            provider_context_limit=provider_context_limit,
        )
        while status.needs_compression and len(folded) > 3:
            folded = [folded[0], *folded[-max(tail_count - 1, 2) :]]
            status = self.budget_manager.evaluate(
                folded,
                config,
                provider_context_limit=provider_context_limit,
            )
            notes.append("tail trimming removed additional context")

        return folded, notes

    def recover_from_error(
        self,
        *,
        session: SessionState,
        config: RuntimeConfig,
        error: Exception,
        provider_context_limit: int | None = None,
        query_source: str = "main",
    ) -> tuple[bool, list[str]]:
        return self.context_manager.recover_from_error(
            session=session,
            runtime_config=config,
            error=error,
            provider_context_limit=provider_context_limit,
            query_source=query_source,
        )

    def on_successful_turn(self, session: SessionState) -> None:
        self.context_manager.on_successful_turn(session)

    def on_tool_result(self, session: SessionState, result) -> None:
        self.context_manager.record_tool_result(session, result)

    def _fold_message(self, message: Message) -> Message:
        if message.role == "tool" or message.metadata.get("tool_result"):
            return message
        if message.folded:
            return message
        if len(message.content) <= 2_000:
            return message
        return Message(
            role=message.role,
            content=message.short(1_400),
            name=message.name,
            tool_call_id=message.tool_call_id,
            metadata={**message.metadata, "folded_reason": "long_message"},
            folded=True,
        )
