from __future__ import annotations

import json
from collections import Counter
from typing import Any

from agent_runtime.schemas import Message


def _safe_json_loads(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return None


def _extract_tool_payload(message: Message) -> dict[str, Any] | None:
    if message.role != "tool":
        return None
    payload = _safe_json_loads(message.content)
    return payload if isinstance(payload, dict) else None


def _tool_name(message: Message) -> str:
    payload = _extract_tool_payload(message)
    if payload and payload.get("tool"):
        return str(payload["tool"])
    if message.name:
        return message.name
    return "tool"


def _extract_file_paths(payload: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for key in ("path", "file_path", "filepath", "filename"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            paths.append(value)
    output = payload.get("output")
    if isinstance(output, dict):
        for key in ("path", "file_path", "filepath", "filename"):
            value = output.get(key)
            if isinstance(value, str) and value:
                paths.append(value)
    return list(dict.fromkeys(paths))


class ConversationSummarizer:
    """Deterministic summarizer used by the context compaction pipeline."""

    def summarize(
        self,
        messages: list[Message],
        *,
        recent_only: bool = False,
        custom_instructions: str | None = None,
    ) -> str:
        user_messages = [message.content for message in messages if message.role == "user"]
        assistant_messages = [
            message.short(300) for message in messages if message.role == "assistant"
        ]
        tool_messages = [message for message in messages if message.role == "tool"]
        tool_counter = Counter(_tool_name(message) for message in tool_messages)

        file_paths: list[str] = []
        errors: list[str] = []
        tool_summaries: list[str] = []
        for message in tool_messages:
            payload = _extract_tool_payload(message)
            if not payload:
                if message.metadata.get("is_error"):
                    errors.append(message.short(240))
                continue
            if payload.get("is_error") or message.metadata.get("is_error"):
                errors.append(str(payload.get("output") or payload.get("summary") or message.content))
            file_paths.extend(_extract_file_paths(payload))
            summary = payload.get("summary")
            if summary:
                tool_summaries.append(f"{_tool_name(message)}: {summary}")

        files_section = "\n".join(f"- {path}" for path in dict.fromkeys(file_paths)) or "- None"
        tool_section = "\n".join(
            f"- {name}: {count} call(s)" for name, count in tool_counter.items()
        ) or "- None"
        user_section = "\n".join(f"- {item}" for item in user_messages) or "- None"
        error_section = "\n".join(f"- {item}" for item in errors) or "- None"
        problem_solving = "\n".join(f"- {item}" for item in tool_summaries[-10:]) or "- None"
        current_work = "\n".join(f"- {item}" for item in assistant_messages[-5:]) or "- None"
        pending = user_messages[-1] if user_messages else "Continue from the preserved tail."
        scope = "recent portion of the conversation" if recent_only else "conversation so far"

        sections = [
            f"Primary Request and Intent:\n- Continue work using the {scope}.",
            "Key Technical Concepts:\n"
            f"{tool_section}",
            "Files and Code Sections:\n"
            f"{files_section}",
            "Errors and Fixes:\n"
            f"{error_section}",
            "Problem Solving:\n"
            f"{problem_solving}",
            "All User Messages:\n"
            f"{user_section}",
            "Pending Tasks:\n"
            f"- {pending}",
            "Current Work:\n"
            f"{current_work}",
            "Optional Next Step:\n"
            "- Resume from the most recent user request with the preserved recent context.",
        ]
        if custom_instructions and custom_instructions.strip():
            sections.append(f"Additional Compact Instructions:\n- {custom_instructions.strip()}")
        return "\n\n".join(sections)
