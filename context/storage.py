from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_runtime.schemas import Message

from .config import ContextConfig
from .types import ContentReplacementRecord

PERSISTED_OUTPUT_TAG = "<persisted-output>"
PERSISTED_OUTPUT_CLOSING_TAG = "</persisted-output>"
TOOL_RESULT_CLEARED_MESSAGE = "[Old tool result content cleared]"


def _preview(content: str, limit: int) -> tuple[str, bool]:
    if len(content) <= limit:
        return content, False
    return content[:limit], True


class ContextStorage:
    def __init__(self, log_dir: str, context_config: ContextConfig) -> None:
        self.root = Path(log_dir).resolve()
        self.config = context_config

    def session_dir(self, session_id: str) -> Path:
        return self.root / session_id / self.config.storage_subdir

    def transcripts_dir(self, session_id: str) -> Path:
        return self.session_dir(session_id) / self.config.transcript_subdir

    def summaries_dir(self, session_id: str) -> Path:
        return self.session_dir(session_id) / self.config.summary_subdir

    def tool_results_dir(self, session_id: str) -> Path:
        return self.session_dir(session_id) / self.config.tool_result_subdir

    def ensure_session_dirs(self, session_id: str) -> None:
        self.transcripts_dir(session_id).mkdir(parents=True, exist_ok=True)
        self.summaries_dir(session_id).mkdir(parents=True, exist_ok=True)
        self.tool_results_dir(session_id).mkdir(parents=True, exist_ok=True)

    def persist_tool_result(
        self,
        session_id: str,
        tool_use_id: str,
        content: str,
        *,
        extension: str = "txt",
    ) -> dict[str, Any]:
        self.ensure_session_dirs(session_id)
        path = self.tool_results_dir(session_id) / f"{tool_use_id}.{extension}"
        if not path.exists():
            path.write_text(content, encoding="utf-8")
        preview, has_more = _preview(content, self.config.tool_result_budget.preview_bytes)
        return {
            "filepath": str(path),
            "original_size": len(content),
            "preview": preview,
            "has_more": has_more,
        }

    def build_large_tool_result_message(self, persisted: dict[str, Any]) -> str:
        lines = [
            PERSISTED_OUTPUT_TAG,
            f"Output too large ({persisted['original_size']} chars). Full output saved to: {persisted['filepath']}",
            "",
            f"Preview (first {self.config.tool_result_budget.preview_bytes} bytes):",
            persisted["preview"],
        ]
        if persisted.get("has_more"):
            lines.append("...")
        lines.append(PERSISTED_OUTPUT_CLOSING_TAG)
        return "\n".join(lines)

    def persist_transcript_segment(
        self,
        session_id: str,
        messages: list[Message],
        *,
        prefix: str,
    ) -> str:
        self.ensure_session_dirs(session_id)
        path = self.transcripts_dir(session_id) / f"{prefix}.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for message in messages:
                handle.write(json.dumps(message.to_dict(), ensure_ascii=False))
                handle.write("\n")
        return str(path)

    def persist_summary(
        self,
        session_id: str,
        summary_text: str,
        *,
        prefix: str,
    ) -> str:
        self.ensure_session_dirs(session_id)
        path = self.summaries_dir(session_id) / f"{prefix}.md"
        path.write_text(summary_text, encoding="utf-8")
        return str(path)

    def persist_content_replacements(
        self,
        session_id: str,
        records: list[ContentReplacementRecord],
    ) -> str:
        self.ensure_session_dirs(session_id)
        path = self.session_dir(session_id) / "content_replacements.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record.to_dict(), ensure_ascii=False))
                handle.write("\n")
        return str(path)
