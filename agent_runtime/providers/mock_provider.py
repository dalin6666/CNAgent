from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator

from ..errors import PromptTooLongError
from ..runtime.budget import estimate_message_tokens, estimate_text_tokens
from ..schemas import Message, ModelChunk, ModelRequest, ToolCall, UsageSnapshot
from .base import BaseModelProvider


class MockModelProvider(BaseModelProvider):
    provider_name = "mock"

    def __init__(
        self,
        model_name: str = "mock-sonnet",
        *,
        provider_id: str | None = None,
        max_context_tokens: int = 8_000,
        max_output_tokens: int = 800,
    ) -> None:
        self.provider_id = provider_id or model_name
        self.model_name = model_name
        self.max_context_tokens = max_context_tokens
        self.max_output_tokens = max_output_tokens

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelChunk]:
        prompt_tokens = sum(estimate_message_tokens(message) for message in request.messages)
        if prompt_tokens > self.max_context_tokens:
            raise PromptTooLongError(
                f"{self.model_name} context exceeded: {prompt_tokens}>{self.max_context_tokens}"
            )

        last_message = request.messages[-1] if request.messages else None
        last_user = self._last_role(request.messages, "user")

        if last_message and last_message.role == "tool":
            answer = self._answer_from_tool(last_message)
            async for chunk in self._stream_text(answer, request.max_output_tokens):
                yield chunk
            return

        read_tool_name = self._select_read_tool(request)
        if last_user and read_tool_name and self._should_call_read_tool(last_user.content):
            file_path = self._extract_path(last_user.content) or "__init__.py"
            yield ModelChunk(
                kind="tool_call",
                tool_call=ToolCall(
                    id=uuid.uuid4().hex[:10],
                    name=read_tool_name,
                    arguments=self._read_arguments(read_tool_name, file_path),
                ),
            )
            yield ModelChunk(kind="done", stop_reason="tool_use")
            return

        glob_tool_name = self._select_glob_tool(request)
        if last_user and glob_tool_name and self._should_call_glob_tool(last_user.content):
            yield ModelChunk(
                kind="tool_call",
                tool_call=ToolCall(
                    id=uuid.uuid4().hex[:10],
                    name=glob_tool_name,
                    arguments=self._glob_arguments(
                        glob_tool_name,
                        request.metadata.get("working_directory", "."),
                    ),
                ),
            )
            yield ModelChunk(kind="done", stop_reason="tool_use")
            return

        answer = self._plain_answer(last_user.content if last_user else "", request)
        async for chunk in self._stream_text(answer, request.max_output_tokens):
            yield chunk

    def _plain_answer(self, prompt: str, request: ModelRequest) -> str:
        continuation_count = int(request.metadata.get("continuation_count", 0))
        prefix = ""
        if continuation_count:
            prefix = f"Continuation {continuation_count}. "
        return (
            f"{prefix}This is a mock Claude-like response for: {prompt.strip() or 'empty input'}. "
            "The runtime skeleton is active, tool calls are available, and you can now replace "
            "this provider with a real OpenAI, Anthropic, or MCP-backed provider."
        )

    def _answer_from_tool(self, tool_message: Message) -> str:
        try:
            payload = json.loads(tool_message.content)
        except json.JSONDecodeError:
            return f"I received tool output:\n{tool_message.content}"

        tool_name = payload.get("tool", tool_message.name or "unknown")
        output = payload.get("output")
        if tool_name == "glob_search" and isinstance(output, dict):
            matches = output.get("matches", [])
            preview = "\n".join(f"- {item}" for item in matches[:12])
            return (
                "I searched the workspace and found these files:\n"
                f"{preview or '- no matches'}\n"
                f"Total matches: {output.get('count', len(matches))}."
            )
        if tool_name == "Glob" and isinstance(output, dict):
            matches = output.get("filenames", [])
            preview = "\n".join(f"- {item}" for item in matches[:12])
            return (
                "I searched the workspace and found these files:\n"
                f"{preview or '- no matches'}\n"
                f"Total matches: {output.get('numFiles', len(matches))}."
            )
        if tool_name == "read_file" and isinstance(output, dict):
            return (
                f"I read {output.get('path', 'the file')}.\n"
                f"Excerpt:\n{output.get('content', '')}"
            )
        if tool_name == "Read" and isinstance(output, dict):
            if output.get("type") == "text" and isinstance(output.get("file"), dict):
                file_payload = output["file"]
                return (
                    f"I read {file_payload.get('filePath', 'the file')}.\n"
                    f"Excerpt:\n{file_payload.get('content', '')}"
                )
            return f"I read a file.\n{json.dumps(output, ensure_ascii=False, indent=2)}"
        return f"I received tool output from {tool_name}:\n{json.dumps(output, ensure_ascii=False, indent=2)}"

    def _should_call_glob_tool(self, prompt: str) -> bool:
        lowered = prompt.lower()
        keywords = ("list", "tree", "directory", "folder", "file", "files", "python", ".py")
        return any(keyword in lowered for keyword in keywords)

    def _should_call_read_tool(self, prompt: str) -> bool:
        lowered = prompt.lower()
        return "read" in lowered or "open" in lowered or bool(self._extract_path(prompt))

    def _select_glob_tool(self, request: ModelRequest) -> str | None:
        available = {tool.get("name") for tool in request.available_tools}
        for candidate in ("Glob", "glob_search"):
            if candidate in available:
                return candidate
        return None

    def _select_read_tool(self, request: ModelRequest) -> str | None:
        available = {tool.get("name") for tool in request.available_tools}
        for candidate in ("Read", "read_file"):
            if candidate in available:
                return candidate
        return None

    def _glob_arguments(self, tool_name: str, working_directory: str) -> dict[str, object]:
        if tool_name == "Glob":
            return {"pattern": "*.py", "path": working_directory}
        return {
            "base_path": working_directory,
            "pattern": "*.py",
            "max_results": 40,
        }

    def _read_arguments(self, tool_name: str, file_path: str) -> dict[str, object]:
        if tool_name == "Read":
            return {"file_path": file_path, "offset": 1, "limit": 120}
        return {"path": file_path, "start_line": 1, "end_line": 120}

    def _extract_path(self, prompt: str) -> str | None:
        matched = re.search(r"[`'\"]([^`'\"]+\.[A-Za-z0-9_]+)[`'\"]", prompt)
        if matched:
            return matched.group(1)
        return None

    def _last_role(self, messages: list[Message], role: str) -> Message | None:
        for message in reversed(messages):
            if message.role == role:
                return message
        return None

    async def _stream_text(
        self,
        text: str,
        requested_output_tokens: int,
    ) -> AsyncIterator[ModelChunk]:
        char_budget = max(requested_output_tokens, 1) * 4
        visible_text = text[:char_budget]
        stop_reason = "max_output_tokens" if len(text) > char_budget else "end_turn"

        for index in range(0, len(visible_text), 32):
            yield ModelChunk(kind="text_delta", text=visible_text[index : index + 32])

        usage = UsageSnapshot(
            input_tokens=estimate_text_tokens(text),
            output_tokens=estimate_text_tokens(visible_text),
            total_tokens=estimate_text_tokens(text) + estimate_text_tokens(visible_text),
        )
        yield ModelChunk(kind="usage", usage=usage)
        yield ModelChunk(kind="done", stop_reason=stop_reason)
