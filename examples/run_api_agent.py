from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_runtime import (
    ModelPolicy,
    RuntimeConfig,
    create_default_runtime,
    deepseek_provider_config,
    openai_provider_config,
    qwen_provider_config,
)
from agent_runtime.events import RuntimeEvent


def build_runtime() -> object:
    provider_name = os.getenv("AGENT_PROVIDER", "openai").strip().lower()
    model_name = os.getenv("AGENT_MODEL", "").strip()

    if provider_name == "deepseek":
        provider = deepseek_provider_config(
            model=model_name or "deepseek-v4-flash",
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        )
    elif provider_name == "qwen":
        provider = qwen_provider_config(
            model=model_name or "qwen-plus",
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url=os.getenv(
                "QWEN_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
        )
    else:
        provider_name = "openai"
        provider = openai_provider_config(
            model=model_name or "gpt-4.1-mini",
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )

    config = RuntimeConfig(
        model_policy=ModelPolicy(
            primary_model=provider_name,
            provider_configs={provider_name: provider},
        ),
        allowed_tool_groups={
            "read",
            "lookup",
            "mcp",
            "exec",
            "state",
            "automation",
            "interactive",
            "agent",
            "write",
        },
    )
    return create_default_runtime(config)


def render_event(event: RuntimeEvent) -> None:
    if event.kind == "text_delta":
        print(event.text, end="", flush=True)
        return
    if event.kind == "tool_delta":
        print(f"[tool_delta] {event.text}")
        return
    if event.kind in {"tool_call", "tool_started", "tool_finished", "model_fallback"}:
        print(f"[{event.kind}] {event.data}")
        return
    if event.kind == "run_finished":
        print(f"\n[run_finished] {event.data.get('stop_reason')}\n")


async def main() -> None:
    runtime = build_runtime()
    prompt = os.getenv(
        "AGENT_PROMPT",
        "Read `__init__.py` and summarize the project briefly.",
    )
    async for event in runtime.stream(prompt, watched_paths=["__init__.py"]):
        render_event(event)


if __name__ == "__main__":
    asyncio.run(main())
