from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_runtime import create_default_runtime
from agent_runtime.events import RuntimeEvent


async def print_events(prompt: str) -> None:
    runtime = create_default_runtime()
    async for event in runtime.stream(
        prompt,
        watched_paths=["__init__.py"],
    ):
        render_event(event)


def render_event(event: RuntimeEvent) -> None:
    if event.kind == "text_delta":
        print(event.text, end="", flush=True)
        return
    if event.kind == "tool_delta":
        print(f"[tool_delta] {event.text}")
        return
    if event.kind == "run_finished":
        print(f"\n[run_finished] {event.data.get('stop_reason')}\n")
    else:
        print(f"[{event.kind}] {event.message}")


async def main() -> None:
    await print_events("List python files in the current directory.")


if __name__ == "__main__":
    asyncio.run(main())
