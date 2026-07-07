from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..config import APIProviderConfig
from ..errors import PromptTooLongError, ProviderExecutionError, ProviderUnavailableError
from ..schemas import ModelChunk, ModelRequest, ToolCall, UsageSnapshot
from .base import BaseModelProvider


class OpenAICompatibleProvider(BaseModelProvider):
    provider_name = "openai_compatible"

    def __init__(self, config: APIProviderConfig) -> None:
        self.config = config
        self.provider_id = config.provider_id
        self.model_name = config.model
        self.max_context_tokens = config.max_context_tokens
        self.max_output_tokens = config.max_output_tokens
        self.supports_streaming = bool(config.stream)
        self.supports_tool_calls = True

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelChunk]:
        api_key = self.config.resolved_api_key()
        if not api_key:
            env_hint = self.config.api_key_env or "API key"
            raise ProviderUnavailableError(
                f"{self.provider_id} is not configured. Set {env_hint} or pass api_key directly."
            )

        tools = self._build_tools(request.available_tools)
        use_stream = self.config.stream and not (
            self.config.disable_streaming_when_tools and bool(tools)
        )
        payload = self._build_payload(request, tools=tools, use_stream=use_stream)
        headers = self._build_headers(api_key)
        url = self._endpoint_url()

        if use_stream:
            async for chunk in self._stream_request(url, headers, payload):
                yield chunk
            return

        async for chunk in self._non_stream_request(url, headers, payload):
            yield chunk

    def _build_payload(
        self,
        request: ModelRequest,
        *,
        tools: list[dict[str, Any]],
        use_stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": self._build_messages(request),
            "stream": use_stream,
            "max_tokens": request.max_output_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if self.config.temperature is not None:
            payload["temperature"] = self.config.temperature
        if self.config.top_p is not None:
            payload["top_p"] = self.config.top_p
        if use_stream and self.config.include_usage_in_stream:
            payload["stream_options"] = {"include_usage": True}
        payload.update(self.config.extra_body)
        return payload

    def _build_headers(self, api_key: str) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if self.config.organization:
            headers["OpenAI-Organization"] = self.config.organization
        if self.config.project:
            headers["OpenAI-Project"] = self.config.project
        headers.update(self.config.headers)
        return headers

    def _endpoint_url(self) -> str:
        base = self.config.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return base + "/chat/completions"

    def _build_tools(self, available_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        for tool in available_tools:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": str(tool.get("name")),
                        "description": str(tool.get("description", "")),
                        "parameters": tool.get("input_schema")
                        if isinstance(tool.get("input_schema"), dict)
                        else {"type": "object", "properties": {}},
                    },
                }
            )
        return tools

    def _build_messages(self, request: ModelRequest) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": request.system_prompt}
        ]
        for message in request.messages:
            if message.role == "assistant" and message.metadata.get("tool_calls"):
                messages.append(
                    {
                        "role": "assistant",
                        "content": message.content or "",
                        "tool_calls": [
                            {
                                "id": str(tool_call.get("id")),
                                "type": "function",
                                "function": {
                                    "name": str(tool_call.get("name")),
                                    "arguments": json.dumps(
                                        tool_call.get("arguments", {}),
                                        ensure_ascii=False,
                                    ),
                                },
                            }
                            for tool_call in message.metadata.get("tool_calls", [])
                        ],
                    }
                )
                continue
            if message.role == "tool":
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": message.tool_call_id or "",
                        "content": message.content,
                    }
                )
                continue
            messages.append({"role": message.role, "content": message.content})
        return messages

    async def _stream_request(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> AsyncIterator[ModelChunk]:
        timeout = httpx.Timeout(self.config.timeout_seconds, connect=30.0)
        partial_tool_calls: dict[int, dict[str, Any]] = {}
        finish_reason: str | None = None
        usage_snapshot: UsageSnapshot | None = None

        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                await self._raise_for_status(response)
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data:
                        continue
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    if isinstance(chunk.get("usage"), dict):
                        usage_snapshot = self._usage_from_payload(chunk["usage"])
                    for choice in chunk.get("choices", []):
                        delta = choice.get("delta") or {}
                        content = delta.get("content")
                        if isinstance(content, str) and content:
                            yield ModelChunk(kind="text_delta", text=content)
                        for tool_delta in delta.get("tool_calls") or []:
                            index = int(tool_delta.get("index", 0))
                            item = partial_tool_calls.setdefault(
                                index,
                                {"id": "", "name": "", "arguments_parts": []},
                            )
                            if tool_delta.get("id"):
                                item["id"] = tool_delta["id"]
                            function = tool_delta.get("function") or {}
                            if function.get("name"):
                                item["name"] = function["name"]
                            if function.get("arguments"):
                                item["arguments_parts"].append(function["arguments"])
                        if choice.get("finish_reason"):
                            finish_reason = str(choice["finish_reason"])

        if usage_snapshot is not None:
            yield ModelChunk(kind="usage", usage=usage_snapshot)
        for tool_call in self._finalize_tool_calls(partial_tool_calls):
            yield ModelChunk(kind="tool_call", tool_call=tool_call)
        yield ModelChunk(kind="done", stop_reason=self._map_stop_reason(finish_reason, bool(partial_tool_calls)))

    async def _non_stream_request(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> AsyncIterator[ModelChunk]:
        timeout = httpx.Timeout(self.config.timeout_seconds, connect=30.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
        await self._raise_for_status(response)
        body = response.json()
        choice = (body.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content") or ""
        if isinstance(content, list):
            content = "".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in content
            )
        if isinstance(content, str) and content:
            for index in range(0, len(content), 64):
                yield ModelChunk(kind="text_delta", text=content[index : index + 64])
        for tool_call in self._tool_calls_from_message(message):
            yield ModelChunk(kind="tool_call", tool_call=tool_call)
        if isinstance(body.get("usage"), dict):
            yield ModelChunk(kind="usage", usage=self._usage_from_payload(body["usage"]))
        finish_reason = choice.get("finish_reason")
        has_tool_calls = bool(message.get("tool_calls"))
        yield ModelChunk(
            kind="done",
            stop_reason=self._map_stop_reason(
                str(finish_reason) if finish_reason is not None else None,
                has_tool_calls,
            ),
        )

    async def _raise_for_status(self, response: httpx.Response) -> None:
        if response.is_success:
            return
        try:
            payload = response.json()
        except Exception:  # noqa: BLE001
            payload = {"error": {"message": response.text}}
        message = self._extract_error_message(payload)
        lowered = message.lower()
        if response.status_code in {400, 413} and any(
            token in lowered
            for token in (
                "maximum context length",
                "context length",
                "prompt too long",
                "too many tokens",
                "max context",
            )
        ):
            raise PromptTooLongError(message)
        raise ProviderExecutionError(
            f"{self.provider_id} request failed ({response.status_code}): {message}"
        )

    def _extract_error_message(self, payload: Any) -> str:
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                if error.get("message"):
                    return str(error["message"])
                if error.get("type"):
                    return str(error["type"])
            if payload.get("message"):
                return str(payload["message"])
        return json.dumps(payload, ensure_ascii=False, default=str)

    def _finalize_tool_calls(
        self,
        partial_tool_calls: dict[int, dict[str, Any]],
    ) -> list[ToolCall]:
        results: list[ToolCall] = []
        for index in sorted(partial_tool_calls):
            raw = partial_tool_calls[index]
            argument_text = "".join(raw.get("arguments_parts", []))
            arguments = self._parse_tool_arguments(argument_text)
            results.append(
                ToolCall(
                    id=str(raw.get("id") or f"toolcall_{index}"),
                    name=str(raw.get("name") or "unknown_tool"),
                    arguments=arguments,
                )
            )
        return results

    def _tool_calls_from_message(self, message: dict[str, Any]) -> list[ToolCall]:
        results: list[ToolCall] = []
        for index, item in enumerate(message.get("tool_calls") or []):
            function = item.get("function") or {}
            arguments = self._parse_tool_arguments(str(function.get("arguments") or ""))
            results.append(
                ToolCall(
                    id=str(item.get("id") or f"toolcall_{index}"),
                    name=str(function.get("name") or "unknown_tool"),
                    arguments=arguments,
                )
            )
        return results

    def _parse_tool_arguments(self, text: str) -> dict[str, Any]:
        if not text.strip():
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"_raw_arguments": text}
        return parsed if isinstance(parsed, dict) else {"_value": parsed}

    def _usage_from_payload(self, payload: dict[str, Any]) -> UsageSnapshot:
        return UsageSnapshot(
            input_tokens=int(payload.get("prompt_tokens", 0) or 0),
            output_tokens=int(payload.get("completion_tokens", 0) or 0),
            total_tokens=int(payload.get("total_tokens", 0) or 0),
        )

    def _map_stop_reason(self, finish_reason: str | None, has_tool_calls: bool) -> str:
        if finish_reason in {"tool_calls", "function_call"} or has_tool_calls:
            return "tool_use"
        if finish_reason == "length":
            return "max_output_tokens"
        if finish_reason in {None, "stop"}:
            return "end_turn"
        return finish_reason
