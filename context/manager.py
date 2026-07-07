from __future__ import annotations

import json
import time
from pathlib import Path

from agent_runtime.config import RuntimeConfig
from agent_runtime.runtime.budget import TokenBudgetManager
from agent_runtime.schemas import Message, SessionState, ToolResult

from .autocompact import AutoCompactor
from .compaction import ConversationCompactor, build_post_compact_messages
from .messages import get_messages_after_compact_boundary
from .microcompact import MicroCompactor
from .reactive import ReactiveCompactor
from .session_memory import SessionMemoryCompactor
from .snip import HistorySnipper
from .state import load_context_state, save_context_state
from .storage import ContextStorage
from .summary import ConversationSummarizer
from .tool_results import (
    enforce_tool_result_budget,
    reconstruct_content_replacement_state,
)
from .types import ContextSessionState


class ContextManager:
    def __init__(
        self,
        *,
        budget_manager: TokenBudgetManager | None = None,
        log_dir: str = ".agent_runtime_logs",
        context_config=None,
    ) -> None:
        self.budget_manager = budget_manager or TokenBudgetManager()
        self.summarizer = ConversationSummarizer()
        self.context_config = context_config
        self.storage = ContextStorage(
            log_dir,
            context_config=context_config or RuntimeConfig().context_config,
        )
        self.conversation_compactor = ConversationCompactor(
            budget_manager=self.budget_manager,
            storage=self.storage,
            summarizer=self.summarizer,
        )
        self.session_memory_compactor = SessionMemoryCompactor(self.budget_manager)
        self.auto_compactor = AutoCompactor(
            budget_manager=self.budget_manager,
            conversation_compactor=self.conversation_compactor,
            session_memory_compactor=self.session_memory_compactor,
        )
        self.micro_compactor = MicroCompactor(self.budget_manager)
        self.reactive_compactor = ReactiveCompactor(
            budget_manager=self.budget_manager,
            conversation_compactor=self.conversation_compactor,
        )
        self.snipper = HistorySnipper(self.budget_manager)

    # 在llm调用之前，整理、裁剪、压缩context信息
    def prepare_messages(
        self,
        *,
        session: SessionState,
        runtime_config: RuntimeConfig,
        provider_context_limit: int | None = None,
        compression_level: int = 0,
        query_source: str = "main",
    ) -> tuple[list[Message], list[str]]:
        state = load_context_state(session)  # 从sessionState中加载ContextSessionState
        self._refresh_last_assistant_timestamp(session, state)
        notes: list[str] = []

        # 如果还没见过Tool Result(state中还没记录处理的tool result),同时session中有Message
        if not state.seen_tool_result_ids and session.messages:
            rebuilt = reconstruct_content_replacement_state(
                session.messages,
                [],
                state,
            )
            save_context_state(session, rebuilt)
            state = rebuilt

        updated_messages, replacement_records, replacement_notes = enforce_tool_result_budget(
            session.messages,
            session.session_id,
            state,
            self.storage,
            runtime_config.context_config.tool_result_budget,
        )
        if replacement_records:
            self.storage.persist_content_replacements(session.session_id, replacement_records)
        if updated_messages != session.messages:
            session.messages = updated_messages
        notes.extend(replacement_notes)

        base_post_boundary = get_messages_after_compact_boundary(
            session.messages,
            include_snipped=True,
        )
        working = list(base_post_boundary)

        snip_result = self.snipper.snip_compact_if_needed(
            working,
            config=runtime_config.context_config.snip,
        )
        working = snip_result.messages
        notes.extend(snip_result.notes)

        micro_result = self.micro_compactor.microcompact_messages(
            working,
            state,
            config=runtime_config.context_config.microcompact,
            query_source=query_source,
        )
        working = micro_result.messages
        notes.extend(micro_result.notes)

        if (
            micro_result.compaction_info is not None
            and micro_result.compaction_info.tokens_saved > 0
            and snip_result.tokens_freed == 0
        ):
            session.messages = self._replace_post_boundary_view(session.messages, working)

        compaction_result, autocompact_notes = self.auto_compactor.auto_compact_if_needed(
            session.session_id,
            working,
            state,
            runtime_config,
            provider_context_limit=provider_context_limit,
            query_source=query_source,
            snip_tokens_freed=snip_result.tokens_freed,
        )
        notes.extend(autocompact_notes)
        if compaction_result is not None:
            session.messages = build_post_compact_messages(compaction_result)
            state.last_compaction_turn = session.turn_count
            state.last_compaction_id = compaction_result.boundary_marker.uuid
            working = list(session.messages)

        working, fallback_notes = self._legacy_tail_compress(
            working,
            runtime_config=runtime_config,
            provider_context_limit=provider_context_limit,
            compression_level=compression_level,
        )
        notes.extend(fallback_notes)
        save_context_state(session, state)
        return working, notes

    def recover_from_error(
        self,
        *,
        session: SessionState,
        runtime_config: RuntimeConfig,
        error: Exception,
        provider_context_limit: int | None = None,
        query_source: str = "main",
    ) -> tuple[bool, list[str]]:
        del provider_context_limit, query_source
        state = load_context_state(session)
        result, notes = self.reactive_compactor.try_reactive_compact(
            session.session_id,
            session.messages,
            state,
            runtime_config,
            error=error,
            has_attempted=bool(state.post_compaction_pending),
        )
        if result is None:
            return False, notes
        session.messages = build_post_compact_messages(result)
        state.post_compaction_pending = True
        state.last_compaction_turn = session.turn_count
        state.last_compaction_id = result.boundary_marker.uuid
        save_context_state(session, state)
        return True, notes

    def on_successful_turn(self, session: SessionState) -> None:
        state = load_context_state(session)
        self.micro_compactor.mark_tools_sent_to_api_state(state)
        self._refresh_last_assistant_timestamp(session, state)
        state.post_compaction_pending = False
        save_context_state(session, state)

    def record_tool_result(self, session: SessionState, result: ToolResult) -> None:
        state = load_context_state(session)
        payload = result.output if isinstance(result.output, dict) else {}

        path = self._first_str(
            payload,
            "path",
            "file_path",
            "filepath",
            "filename",
        )
        content = self._extract_content(payload)
        tool_name = result.name
        if path and content and tool_name in {"Read", "read_file"}:
            state.read_history[str(Path(path).resolve())] = self._read_history_entry(
                path,
                content,
            )

        if tool_name in {"Skill", "skill"}:
            skill_name = self._first_str(payload, "name", "skill_name") or "skill"
            skill_path = self._first_str(payload, "path", "skill_path") or ""
            skill_content = content or json.dumps(payload, ensure_ascii=False, default=str)
            state.invoked_skills.append(
                self._skill_record(skill_name, skill_path, skill_content)
            )

        if tool_name in {"EnterPlanMode", "EnterPlanModeTool"}:
            state.plan_mode_active = True
        if tool_name in {"ExitPlanMode", "ExitPlanModeTool"}:
            state.plan_mode_active = False

        if tool_name in {"Write", "Edit", "FileWriteTool"} and path:
            plan_hint = Path(path).name.lower()
            if "plan" in plan_hint:
                state.plan_path = str(path)
                state.plan_content = content

        save_context_state(session, state)

    def _replace_post_boundary_view(
        self,
        full_messages: list[Message],
        post_boundary_messages: list[Message],
    ) -> list[Message]:
        boundary_index = -1
        for index in range(len(full_messages) - 1, -1, -1):
            message = full_messages[index]
            if message.role == "system" and message.subtype == "compact_boundary":
                boundary_index = index
                break
        prefix = full_messages[:boundary_index] if boundary_index != -1 else []
        return [*prefix, *post_boundary_messages]

    def _legacy_tail_compress(
        self,
        messages: list[Message],
        *,
        runtime_config: RuntimeConfig,
        provider_context_limit: int | None = None,
        compression_level: int = 0,
    ) -> tuple[list[Message], list[str]]:
        status = self.budget_manager.evaluate(
            messages,
            runtime_config,
            provider_context_limit=provider_context_limit,
        )
        if not status.needs_compression:
            return list(messages), []

        notes: list[str] = []
        tail_count = max(runtime_config.compression_tail_messages - compression_level, 3)
        summary_count = max(runtime_config.compression_summary_messages + compression_level, 4)
        tail = list(messages[-tail_count:])
        older = list(messages[:-tail_count])
        if older:
            summary_lines = [f"{message.role}: {message.short(160)}" for message in older[-summary_count:]]
            summary_message = Message(
                role="system",
                content="Compressed conversation summary:\n" + "\n".join(summary_lines),
                metadata={"compressed": True, "compression_level": compression_level},
                folded=True,
            )
            compressed = [summary_message, *tail]
            notes.append("legacy tail compression summarized older messages")
        else:
            compressed = tail
        status = self.budget_manager.evaluate(
            compressed,
            runtime_config,
            provider_context_limit=provider_context_limit,
        )
        while status.needs_compression and len(compressed) > 3:
            compressed = [compressed[0], *compressed[-max(tail_count - 1, 2) :]]
            status = self.budget_manager.evaluate(
                compressed,
                runtime_config,
                provider_context_limit=provider_context_limit,
            )
            notes.append("legacy tail compression trimmed more preserved tail context")
        return compressed, notes

    def _refresh_last_assistant_timestamp(
        self,
        session: SessionState,
        state: ContextSessionState,
    ) -> None:
        for message in reversed(session.messages):
            if message.role == "assistant":
                state.last_assistant_timestamp = message.timestamp
                break

    def _first_str(self, payload: dict[str, object], *keys: str) -> str | None:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
            output = payload.get("output")
            if isinstance(output, dict):
                nested = output.get(key)
                if isinstance(nested, str) and nested:
                    return nested
        return None

    def _extract_content(self, payload: dict[str, object]) -> str | None:
        value = payload.get("content")
        if isinstance(value, str):
            return value
        output = payload.get("output")
        if isinstance(output, dict):
            nested = output.get("content")
            if isinstance(nested, str):
                return nested
            return json.dumps(output, ensure_ascii=False, default=str)
        if output is not None:
            return json.dumps(output, ensure_ascii=False, default=str)
        return None

    def _read_history_entry(self, path: str, content: str):
        from .types import ReadHistoryEntry

        return ReadHistoryEntry(path=path, content=content, timestamp=time.time())

    def _skill_record(self, name: str, path: str, content: str):
        from .types import InvokedSkillRecord

        return InvokedSkillRecord(
            name=name,
            path=path,
            content=content,
            invoked_at=time.time(),
        )
