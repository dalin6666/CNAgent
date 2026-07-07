from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from agent_runtime.runtime.budget import TokenBudgetManager
from agent_runtime.schemas import Message

from .config import ContextConfig, PostCompactRestoreConfig
from .messages import (
    annotate_boundary_with_preserved_segment,
    create_attachment_message,
    create_compact_boundary_message,
    create_compact_summary_message,
    get_messages_after_compact_boundary,
)
from .prompt import get_compact_user_summary_message
from .storage import ContextStorage
from .summary import ConversationSummarizer
from .types import ArchivedSegment, CompactionResult, ContextSessionState


def build_post_compact_messages(result: CompactionResult) -> list[Message]:
    return [
        result.boundary_marker,
        *result.summary_messages,
        *result.messages_to_keep,
        *result.attachments,
        *result.hook_results,
    ]


def merge_hook_instructions(
    user_instructions: str | None,
    hook_instructions: str | None,
) -> str | None:
    if not hook_instructions:
        return user_instructions or None
    if not user_instructions:
        return hook_instructions
    return f"{user_instructions}\n\n{hook_instructions}"


class ConversationCompactor:
    def __init__(
        self,
        *,
        budget_manager: TokenBudgetManager | None = None,
        storage: ContextStorage,
        summarizer: ConversationSummarizer | None = None,
    ) -> None:
        self.budget_manager = budget_manager or TokenBudgetManager()
        self.storage = storage
        self.summarizer = summarizer or ConversationSummarizer()

    def compact_conversation(
        self,
        session_id: str,
        messages: list[Message],
        state: ContextSessionState,
        context_config: ContextConfig,
        *,
        custom_instructions: str | None = None,
        trigger: str = "auto",
        preserve_tail_messages: int | None = None,
    ) -> CompactionResult:
        if not messages:
            raise ValueError("cannot compact an empty conversation")

        working = get_messages_after_compact_boundary(messages, include_snipped=True)
        pre_compact_tokens = self.budget_manager.estimate_prompt_tokens(working)
        tail_count = preserve_tail_messages or context_config.auto.summary_keep_tail_messages
        tail_count = max(tail_count, 3)
        keep_start = max(len(working) - tail_count, 0)
        keep_start = self._adjust_keep_start_for_tool_pairs(working, keep_start)

        messages_to_summarize = working[:keep_start]
        messages_to_keep = list(working[keep_start:])
        if not messages_to_summarize:
            messages_to_summarize = working[:-1]
            messages_to_keep = [working[-1]]

        transcript_prefix = (
            f"{trigger}-compact-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        )
        transcript_path = self.storage.persist_transcript_segment(
            session_id,
            messages_to_summarize,
            prefix=transcript_prefix,
        )
        summary_text = self.summarizer.summarize(
            messages_to_summarize,
            recent_only=False,
            custom_instructions=custom_instructions,
        )
        self.storage.persist_summary(
            session_id,
            summary_text,
            prefix=transcript_prefix,
        )
        summary_message = create_compact_summary_message(
            get_compact_user_summary_message(
                summary_text,
                suppress_follow_up_questions=True,
                transcript_path=transcript_path,
                recent_messages_preserved=bool(messages_to_keep),
            ),
            recent_messages_preserved=bool(messages_to_keep),
        )

        boundary = create_compact_boundary_message(
            trigger,
            pre_compact_tokens,
            messages_to_summarize[-1].uuid if messages_to_summarize else working[-1].uuid,
            messages_summarized=len(messages_to_summarize),
        )
        boundary = annotate_boundary_with_preserved_segment(
            boundary,
            summary_message.uuid,
            messages_to_keep,
        )

        attachments = [
            *self.create_post_compact_file_attachments(
                state,
                restore_config=context_config.restore,
                preserved_messages=messages_to_keep,
            ),
        ]
        plan_attachment = self.create_plan_attachment_if_needed(state)
        if plan_attachment is not None:
            attachments.append(plan_attachment)
        skill_attachment = self.create_skill_attachment_if_needed(
            state,
            restore_config=context_config.restore,
        )
        if skill_attachment is not None:
            attachments.append(skill_attachment)
        plan_mode_attachment = self.create_plan_mode_attachment_if_needed(state)
        if plan_mode_attachment is not None:
            attachments.append(plan_mode_attachment)
        attachments.extend(self.create_async_agent_attachments_if_needed(state))

        state.session_memory_sections.append(summary_text)
        state.last_summarized_message_uuid = (
            messages_to_summarize[-1].uuid if messages_to_summarize else None
        )
        state.archived_segments.append(
            self._archived_segment(
                transcript_path,
                trigger,
                len(messages_to_summarize),
                summary_message.uuid,
            )
        )

        return CompactionResult(
            boundary_marker=boundary,
            summary_messages=[summary_message],
            attachments=attachments,
            hook_results=[],
            messages_to_keep=messages_to_keep,
            pre_compact_token_count=pre_compact_tokens,
            post_compact_token_count=self.budget_manager.estimate_prompt_tokens(
                [boundary, summary_message]
            ),
            true_post_compact_token_count=self.budget_manager.estimate_prompt_tokens(
                [boundary, summary_message, *messages_to_keep, *attachments]
            ),
            transcript_path=transcript_path,
            trigger=trigger,
        )

    def partial_compact_conversation(
        self,
        session_id: str,
        messages: list[Message],
        state: ContextSessionState,
        context_config: ContextConfig,
        *,
        keep_from_index: int,
        custom_instructions: str | None = None,
    ) -> CompactionResult:
        keep_from_index = max(0, min(keep_from_index, len(messages)))
        messages_to_keep = list(messages[keep_from_index:])
        messages_to_summarize = list(messages[:keep_from_index])
        if not messages_to_summarize:
            return self.compact_conversation(
                session_id,
                messages,
                state,
                context_config,
                custom_instructions=custom_instructions,
                trigger="manual",
            )

        transcript_prefix = (
            f"partial-compact-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        )
        transcript_path = self.storage.persist_transcript_segment(
            session_id,
            messages_to_summarize,
            prefix=transcript_prefix,
        )
        summary_text = self.summarizer.summarize(
            messages_to_summarize,
            recent_only=True,
            custom_instructions=custom_instructions,
        )
        summary_message = create_compact_summary_message(
            get_compact_user_summary_message(
                summary_text,
                suppress_follow_up_questions=True,
                transcript_path=transcript_path,
                recent_messages_preserved=True,
            ),
            recent_messages_preserved=True,
        )
        boundary = create_compact_boundary_message(
            "manual",
            self.budget_manager.estimate_prompt_tokens(messages),
            messages_to_summarize[-1].uuid,
            messages_summarized=len(messages_to_summarize),
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
            post_compact_token_count=self.budget_manager.estimate_prompt_tokens(
                [boundary, summary_message]
            ),
            true_post_compact_token_count=self.budget_manager.estimate_prompt_tokens(
                [boundary, summary_message, *messages_to_keep]
            ),
            transcript_path=transcript_path,
            trigger="manual",
        )

    def truncate_head_for_ptl_retry(
        self,
        messages: list[Message],
        *,
        max_messages: int,
    ) -> list[Message]:
        if len(messages) <= max_messages:
            return list(messages)
        truncated = list(messages[-max_messages:])
        return truncated

    def strip_attachment_messages(self, messages: list[Message]) -> list[Message]:
        return [
            message
            for message in messages
            if not (
                message.role == "system"
                and (
                    message.subtype == "context_attachment"
                    or message.metadata.get("source") == "attachment"
                )
            )
        ]

    def create_post_compact_file_attachments(
        self,
        state: ContextSessionState,
        *,
        restore_config: PostCompactRestoreConfig,
        preserved_messages: list[Message],
    ) -> list[Message]:
        preserved_paths = self._collect_read_paths_from_messages(preserved_messages)
        recent_entries = sorted(
            state.read_history.values(),
            key=lambda item: item.timestamp,
            reverse=True,
        )
        attachments: list[Message] = []
        used_tokens = 0
        for entry in recent_entries[: restore_config.max_files_to_restore]:
            normalized = str(Path(entry.path).resolve())
            if normalized in preserved_paths:
                continue
            truncated_content = entry.content[: restore_config.max_tokens_per_file * 4]
            candidate = create_attachment_message(
                (
                    "Post-compact file restore.\n"
                    f"Path: {entry.path}\n"
                    "Content preview:\n"
                    f"{truncated_content}"
                ),
                attachment_type="post_compact_file",
                payload={"path": entry.path},
            )
            tokens = self.budget_manager.estimate_prompt_tokens([candidate])
            if used_tokens + tokens > restore_config.file_restore_token_budget:
                continue
            used_tokens += tokens
            attachments.append(candidate)
        return attachments

    def create_plan_attachment_if_needed(
        self,
        state: ContextSessionState,
    ) -> Message | None:
        if not state.plan_content or not state.plan_path:
            return None
        return create_attachment_message(
            (
                "Plan file preserved across compaction.\n"
                f"Path: {state.plan_path}\n"
                f"Content:\n{state.plan_content}"
            ),
            attachment_type="plan_file_reference",
            payload={"plan_path": state.plan_path},
        )

    def create_skill_attachment_if_needed(
        self,
        state: ContextSessionState,
        *,
        restore_config: PostCompactRestoreConfig,
    ) -> Message | None:
        if not state.invoked_skills:
            return None
        used_tokens = 0
        skill_payloads: list[dict[str, str]] = []
        for skill in sorted(state.invoked_skills, key=lambda item: item.invoked_at, reverse=True):
            content = skill.content[: restore_config.max_tokens_per_skill * 4]
            tokens = max(1, len(content) // 4)
            if used_tokens + tokens > restore_config.skill_restore_token_budget:
                continue
            used_tokens += tokens
            skill_payloads.append(
                {"name": skill.name, "path": skill.path, "content": content}
            )
        if not skill_payloads:
            return None
        return create_attachment_message(
            "Invoked skills preserved across compaction.\n"
            + json.dumps(skill_payloads, ensure_ascii=False, indent=2),
            attachment_type="invoked_skills",
        )

    def create_plan_mode_attachment_if_needed(
        self,
        state: ContextSessionState,
    ) -> Message | None:
        if not state.plan_mode_active:
            return None
        return create_attachment_message(
            "Plan mode is still active after compaction. Continue operating in planning mode.",
            attachment_type="plan_mode",
            payload={"plan_exists": bool(state.plan_content)},
        )

    def create_async_agent_attachments_if_needed(
        self,
        state: ContextSessionState,
    ) -> list[Message]:
        attachments: list[Message] = []
        for agent in state.async_agents:
            if agent.retrieved:
                continue
            attachments.append(
                create_attachment_message(
                    (
                        "Background agent state preserved across compaction.\n"
                        f"Task ID: {agent.task_id}\n"
                        f"Status: {agent.status}\n"
                        f"Description: {agent.description}\n"
                        f"Delta: {agent.delta_summary}"
                    ),
                    attachment_type="async_agent",
                    payload={"task_id": agent.task_id, "status": agent.status},
                )
            )
        return attachments

    def _collect_read_paths_from_messages(self, messages: list[Message]) -> set[str]:
        paths: set[str] = set()
        for message in messages:
            if message.role != "tool":
                continue
            try:
                payload = json.loads(message.content)
            except Exception:  # noqa: BLE001
                continue
            output = payload.get("output")
            if isinstance(output, dict):
                for key in ("path", "file_path", "filepath", "filename"):
                    value = output.get(key)
                    if isinstance(value, str):
                        paths.add(str(Path(value).resolve()))
            for key in ("path", "file_path", "filepath", "filename"):
                value = payload.get(key)
                if isinstance(value, str):
                    paths.add(str(Path(value).resolve()))
        return paths

    def _adjust_keep_start_for_tool_pairs(
        self,
        messages: list[Message],
        keep_start: int,
    ) -> int:
        if keep_start <= 0 or keep_start >= len(messages):
            return keep_start
        tool_ids = {
            message.tool_call_id
            for message in messages[keep_start:]
            if message.role == "tool" and message.tool_call_id
        }
        if not tool_ids:
            return keep_start
        adjusted = keep_start
        for index in range(keep_start - 1, -1, -1):
            message = messages[index]
            if message.role != "assistant":
                continue
            tool_calls = message.metadata.get("tool_calls", [])
            if any(
                isinstance(tool_call, dict)
                and str(tool_call.get("id", "")) in tool_ids
                for tool_call in tool_calls
            ):
                adjusted = index
        return adjusted

    def _archived_segment(
        self,
        path: str,
        kind: str,
        message_count: int,
        summary_uuid: str,
    ) -> ArchivedSegment:
        return ArchivedSegment(
            path=path,
            kind=kind,
            created_at=datetime.now(timezone.utc).isoformat(),
            message_count=message_count,
            summary_uuid=summary_uuid,
        )
