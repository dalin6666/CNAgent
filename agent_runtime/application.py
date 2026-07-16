from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from .config import (
    ModelPolicy,
    RuntimeConfig,
    deepseek_provider_config,
    openai_provider_config,
    qwen_provider_config,
)
from .runtime.engine import AgentRuntime, create_default_runtime
from .schemas import SessionState

ALL_TOOL_GROUPS = {
    "read",
    "lookup",
    "mcp",
    "exec",
    "state",
    "automation",
    "interactive",
    "agent",
    "write",
}

WEB_SAFE_TOOL_GROUPS = {"read", "lookup"}

PROVIDER_CHOICES = ("mock", "openai", "deepseek", "qwen")


def normalize_provider(provider: str | None = None) -> str:
    provider_name = (provider or os.getenv("AGENT_PROVIDER", "deepseek")).strip().lower()
    if provider_name not in PROVIDER_CHOICES:
        allowed = ", ".join(PROVIDER_CHOICES)
        raise ValueError(f"Unsupported provider '{provider_name}'. Allowed: {allowed}.")
    return provider_name


def build_runtime_from_env(
    *,
    provider: str | None = None,
    model: str | None = None,
    workdir: str | os.PathLike[str] = ".",
    allowed_tool_groups: Iterable[str] | None = None,
    require_api_key: bool = True,
) -> AgentRuntime:
    resolved_workdir = str(Path(workdir).expanduser().resolve())
    provider_name = normalize_provider(provider)
    model_name = (model if model is not None else os.getenv("AGENT_MODEL", "")).strip()
    tool_groups = set(allowed_tool_groups or WEB_SAFE_TOOL_GROUPS)

    if provider_name == "mock":
        return create_default_runtime(
            RuntimeConfig(
                working_directory=resolved_workdir,
                allowed_tool_groups=tool_groups,
            )
        )

    api_key_env = {
        "deepseek": "DEEPSEEK_API_KEY",
        "qwen": "DASHSCOPE_API_KEY",
        "openai": "OPENAI_API_KEY",
    }[provider_name]
    if require_api_key and not os.getenv(api_key_env):
        raise RuntimeError(
            f"{provider_name} requires {api_key_env}. "
            f"Set it before using the web chat."
        )

    if provider_name == "deepseek":
        provider_config = deepseek_provider_config(
            model=model_name or "deepseek-v4-flash",
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            extra_body=_deepseek_extra_body(),
        )
    elif provider_name == "qwen":
        provider_config = qwen_provider_config(
            model=model_name or "qwen-plus",
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url=os.getenv(
                "QWEN_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
        )
    else:
        provider_config = openai_provider_config(
            model=model_name or "gpt-4.1-mini",
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )

    return create_default_runtime(
        RuntimeConfig(
            working_directory=resolved_workdir,
            model_policy=ModelPolicy(
                primary_model=provider_name,
                fallback_models=[],
                provider_configs={provider_name: provider_config},
            ),
            allowed_tool_groups=tool_groups,
        )
    )


def new_session(workdir: str | os.PathLike[str]) -> SessionState:
    session = SessionState()
    session.metadata["working_directory"] = str(Path(workdir).expanduser().resolve())
    return session


def prepare_next_run(session: SessionState) -> None:
    session.turn_count = 0
    session.continuation_count = 0
    session.finished = False


def _deepseek_extra_body() -> dict[str, object]:
    thinking_mode = os.getenv("DEEPSEEK_THINKING", "disabled").strip().lower()
    if thinking_mode not in {"enabled", "disabled"}:
        thinking_mode = "disabled"

    body: dict[str, object] = {"thinking": {"type": thinking_mode}}
    if thinking_mode == "enabled":
        effort = os.getenv("DEEPSEEK_REASONING_EFFORT", "high").strip().lower()
        if effort not in {"high", "max"}:
            effort = "high"
        body["reasoning_effort"] = effort
    return body
