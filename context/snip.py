from __future__ import annotations

from agent_runtime.runtime.budget import TokenBudgetManager
from agent_runtime.schemas import Message

from .config import SnipConfig
from .messages import create_system_message
from .types import SnipResult


def project_snipped_view(messages: list[Message]) -> list[Message]:
    return [message for message in messages if not message.metadata.get("snipped")]


def apply_snip_removals(messages: list[Message], removed_message_ids: set[str]) -> list[Message]:
    result: list[Message] = []
    for message in messages:
        if message.uuid in removed_message_ids:
            result.append(
                Message(
                    role=message.role,
                    content=message.content,
                    name=message.name,
                    tool_call_id=message.tool_call_id,
                    metadata={**message.metadata, "snipped": True, "snip_hidden": True},
                    folded=message.folded,
                    timestamp=message.timestamp,
                    uuid=message.uuid,
                    subtype=message.subtype,
                    is_meta=message.is_meta,
                )
            )
        else:
            result.append(message)
    return result


class HistorySnipper:
    def __init__(self, budget_manager: TokenBudgetManager | None = None) -> None:
        self.budget_manager = budget_manager or TokenBudgetManager()

    def snip_compact_if_needed(
        self,
        messages: list[Message],
        *,
        config: SnipConfig,
    ) -> SnipResult:
        if not config.enabled or len(messages) < config.trigger_message_count:
            return SnipResult(messages=list(messages))

        head = list(messages[: config.protected_head_messages])
        tail_start = max(len(messages) - config.protected_tail_messages, len(head))
        tail_start = self._adjust_start_for_tool_pairs(messages, tail_start)
        middle = messages[len(head) : tail_start]
        tail = list(messages[tail_start:])

        if len(middle) < config.min_messages_to_snip:
            return SnipResult(messages=list(messages))

        removed_tokens = self.budget_manager.estimate_prompt_tokens(list(middle))
        removed_ids = {message.uuid for message in middle}
        boundary = create_system_message(
            "Older context was snipped from the working view to preserve prompt budget.",
            subtype="snip_boundary",
            metadata={
                "tokens_freed": removed_tokens,
                "removed_message_ids": sorted(removed_ids),
            },
        )
        working = [*head, boundary, *tail]
        notes = [f"history snip removed {len(middle)} message(s) from the middle of context"]
        return SnipResult(
            messages=working,
            tokens_freed=removed_tokens,
            boundary_message=boundary,
            notes=notes,
        )

    def _adjust_start_for_tool_pairs(self, messages: list[Message], start_index: int) -> int:
        if start_index <= 0 or start_index >= len(messages):
            return start_index
        kept_tool_ids = {
            message.tool_call_id
            for message in messages[start_index:]
            if message.role == "tool" and message.tool_call_id
        }
        if not kept_tool_ids:
            return start_index

        adjusted = start_index
        for index in range(start_index - 1, -1, -1):
            message = messages[index]
            if message.role != "assistant":
                continue
            tool_calls = message.metadata.get("tool_calls", [])
            if any(
                isinstance(tool_call, dict)
                and str(tool_call.get("id", "")) in kept_tool_ids
                for tool_call in tool_calls
            ):
                adjusted = index
        return adjusted
