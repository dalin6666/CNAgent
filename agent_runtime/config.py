from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from context.config import ContextConfig


@dataclass(slots=True)
class APIProviderConfig:
    provider_id: str
    model: str
    base_url: str
    api_key: str | None = None
    api_key_env: str | None = None
    provider_type: str = "openai_compatible"
    timeout_seconds: float = 120.0
    max_context_tokens: int = 128_000
    max_output_tokens: int = 8_192
    temperature: float | None = None
    top_p: float | None = None
    headers: dict[str, str] = field(default_factory=dict)
    extra_body: dict[str, Any] = field(default_factory=dict)
    stream: bool = True
    include_usage_in_stream: bool = True
    disable_streaming_when_tools: bool = False
    organization: str | None = None
    project: str | None = None

    def resolved_api_key(self) -> str | None:
        if self.api_key:
            return self.api_key
        if self.api_key_env:
            return os.getenv(self.api_key_env)
        return None


def openai_provider_config(
    *,
    provider_id: str = "openai",
    model: str = "gpt-4.1-mini",
    api_key: str | None = None,
    api_key_env: str = "OPENAI_API_KEY",
    base_url: str = "https://api.openai.com/v1",
    **kwargs: Any,
) -> APIProviderConfig:
    return APIProviderConfig(
        provider_id=provider_id,
        model=model,
        api_key=api_key,
        api_key_env=api_key_env,
        base_url=base_url,
        **kwargs,
    )


def deepseek_provider_config(
    *,
    provider_id: str = "deepseek",
    model: str = "deepseek-v4-flash",
    api_key: str | None = None,
    api_key_env: str = "DEEPSEEK_API_KEY",
    base_url: str = "https://api.deepseek.com",
    **kwargs: Any,
) -> APIProviderConfig:
    return APIProviderConfig(
        provider_id=provider_id,
        model=model,
        api_key=api_key,
        api_key_env=api_key_env,
        base_url=base_url,
        **kwargs,
    )


def qwen_provider_config(
    *,
    provider_id: str = "qwen",
    model: str = "qwen-plus",
    api_key: str | None = None,
    api_key_env: str = "DASHSCOPE_API_KEY",
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
    disable_streaming_when_tools: bool = True,
    **kwargs: Any,
) -> APIProviderConfig:
    return APIProviderConfig(
        provider_id=provider_id,
        model=model,
        api_key=api_key,
        api_key_env=api_key_env,
        base_url=base_url,
        disable_streaming_when_tools=disable_streaming_when_tools,
        **kwargs,
    )


@dataclass(slots=True)
class ModelPolicy:
    primary_model: str = "mock-sonnet"
    fallback_models: list[str] = field(default_factory=lambda: ["mock-haiku"])
    provider_configs: dict[str, APIProviderConfig] = field(default_factory=dict)

# 装饰器，自动生成构造函数，减少对象内存占用，限制只能用预定义的字段
@dataclass(slots=True)
class RuntimeConfig:
    model_policy: ModelPolicy = field(default_factory=ModelPolicy)
    system_prompt: str = (
        "You are a Claude-like coding agent. Think step by step, call tools when "
        "needed, and finish the task safely."
    )
    working_directory: str = "."  # 工作根目录
    max_turns: int = 12  # 最多内部循环数
    context_window_tokens: int = 16_000 # context窗口
    reserved_output_tokens: int = 2_000 # 预留output窗口
    max_output_tokens: int = 800 # 单词model输出最大值
    prompt_too_long_retries: int = 2 # 最大尝试次数（）context超标
    max_continuations: int = 2
    compression_tail_messages: int = 8
    compression_summary_messages: int = 10
    max_attachment_chars: int = 2_000
    max_file_change_items: int = 10
    enable_attachment_injection: bool = True
    enable_memory_prefetch: bool = True
    enable_skill_prefetch: bool = True
    enable_mcp_discovery: bool = True
    enable_legacy_tool_adapters: bool = True
    log_dir: str = ".agent_runtime_logs"
    continue_prompt: str = "Continue exactly where you stopped."
    context_config: ContextConfig = field(default_factory=ContextConfig)
    allowed_tool_groups: set[str] = field(
        default_factory=lambda: {"read", "lookup", "mcp"}
    )
