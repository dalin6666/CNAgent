from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

MIN_PYTHON = (3, 10)
if sys.version_info < MIN_PYTHON:
    current = ".".join(str(part) for part in sys.version_info[:3])
    required = ".".join(str(part) for part in MIN_PYTHON)
    raise SystemExit(
        f"Python {required} or newer is required (current: {current}). "
        "Activate a newer environment, for example: conda activate agent"
    )

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_runtime import (
    ModelPolicy,
    RuntimeConfig,
    SessionState,
    create_default_runtime,
    deepseek_provider_config,
    openai_provider_config,
    qwen_provider_config,
)
from agent_runtime.events import RuntimeEvent


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interactive command-line client for the existing AgentRuntime.",
    )
    parser.add_argument(
        "--provider",
        choices=("mock", "openai", "deepseek", "qwen"),
        default=os.getenv("AGENT_PROVIDER", "deepseek").strip().lower(),
        help="Model provider. Defaults to AGENT_PROVIDER or deepseek.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("AGENT_MODEL", "").strip(),
        help="Model name. Defaults to AGENT_MODEL or the provider preset.",
    )
    parser.add_argument(
        "--workdir",
        default=str(ROOT),
        help="Working directory exposed to runtime tools.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show runtime lifecycle events and tool arguments.",
    )
    return parser.parse_args()


def build_runtime(args: argparse.Namespace):
    workdir = str(Path(args.workdir).expanduser().resolve())
    provider_name = args.provider

    if provider_name == "mock":
        config = RuntimeConfig(
            working_directory=workdir,
            allowed_tool_groups=set(ALL_TOOL_GROUPS),
        )
        return create_default_runtime(config)

    api_key_env = {
        "deepseek": "DEEPSEEK_API_KEY",
        "qwen": "DASHSCOPE_API_KEY",
        "openai": "OPENAI_API_KEY",
    }[provider_name]
    if not os.getenv(api_key_env):
        raise SystemExit(
            f"{provider_name} requires {api_key_env}. "
            f"Set it in PowerShell with: $env:{api_key_env} = 'your-api-key'"
        )

    if provider_name == "deepseek":
        provider = deepseek_provider_config(
            model=args.model or "deepseek-v4-flash",
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        )
    elif provider_name == "qwen":
        provider = qwen_provider_config(
            model=args.model or "qwen-plus",
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url=os.getenv(
                "QWEN_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
        )
    else:
        provider = openai_provider_config(
            model=args.model or "gpt-4.1-mini",
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )

    config = RuntimeConfig(
        working_directory=workdir,
        model_policy=ModelPolicy(
            primary_model=provider_name,
            fallback_models=[],
            provider_configs={provider_name: provider},
        ),
        allowed_tool_groups=set(ALL_TOOL_GROUPS),
    )
    return create_default_runtime(config)


def new_session(workdir: str) -> SessionState:
    session = SessionState()
    session.metadata["working_directory"] = workdir
    return session


def prepare_next_run(session: SessionState) -> None:
    # AgentRuntime limits turns per stream() call. Keep conversation messages and
    # usage, while resetting only state that belongs to the previous CLI request.
    session.turn_count = 0
    session.continuation_count = 0
    session.finished = False


def print_banner(args: argparse.Namespace, runtime) -> None:
    model = runtime.providers[0].model_name if runtime.providers else "unknown"
    print("Agent Runtime CLI")
    print(f"Provider: {args.provider} | Model: {model}")
    print(f"Working directory: {runtime.config.working_directory}")
    print("Type /help for commands. Press Ctrl+C to cancel input, /exit to quit.")


def print_help() -> None:
    print(
        "\nCommands:\n"
        "  /help       Show this help\n"
        "  /new        Start a new conversation\n"
        "  /status     Show session and token usage\n"
        "  /verbose    Toggle detailed runtime events\n"
        "  /exit       Exit the CLI\n"
    )


def print_status(session: SessionState, runtime, verbose: bool) -> None:
    usage = session.usage
    print(f"Session: {session.session_id}")
    print(f"Model: {session.active_model or runtime.providers[0].model_name}")
    print(f"Messages: {len(session.messages)}")
    print(
        "Tokens: "
        f"input={usage.input_tokens}, output={usage.output_tokens}, "
        f"total={usage.total_tokens}"
    )
    print(f"Verbose: {'on' if verbose else 'off'}")


class EventRenderer:
    def __init__(self, *, verbose: bool) -> None:
        self.verbose = verbose
        self.answer_started = False

    def render(self, event: RuntimeEvent) -> None:
        if event.kind == "text_delta":
            if not self.answer_started:
                print("Assistant> ", end="", flush=True)
                self.answer_started = True
            print(event.text, end="", flush=True)
            return

        if event.kind == "tool_call":
            self._finish_answer_line()
            tool = event.data.get("tool", "unknown")
            print(f"[tool] calling {tool}")
            if self.verbose:
                arguments = json.dumps(
                    event.data.get("arguments", {}),
                    ensure_ascii=False,
                    default=str,
                )
                print(f"       arguments: {arguments}")
            return

        if event.kind == "tool_delta" and self.verbose:
            self._finish_answer_line()
            print(f"[tool output] {event.text}", end="", flush=True)
            return

        if event.kind == "tool_finished":
            self._finish_answer_line()
            tool = event.data.get("tool", "unknown")
            duration = float(event.data.get("duration_ms", 0.0))
            status = "error" if event.data.get("is_error") else "done"
            print(f"[tool] {tool}: {status} ({duration:.0f} ms)")
            if self.verbose and event.data.get("summary"):
                print(f"       {event.data['summary']}")
            return

        if event.kind == "model_fallback":
            self._finish_answer_line()
            error = event.data.get("error") or event.data.get("reason") or event.message
            print(f"[provider error] {error}")
            return

        if event.kind == "recovery":
            self._finish_answer_line()
            print(f"[recovery] {event.message}")
            return

        if self.verbose and event.kind not in {"tool_started"}:
            self._finish_answer_line()
            print(f"[{event.kind}] {event.message}")

    def finish(self) -> None:
        self._finish_answer_line()

    def _finish_answer_line(self) -> None:
        if self.answer_started:
            print()
            self.answer_started = False


async def run_prompt(runtime, session: SessionState, prompt: str, verbose: bool) -> None:
    prepare_next_run(session)
    renderer = EventRenderer(verbose=verbose)
    try:
        async for event in runtime.stream(prompt, session=session):
            renderer.render(event)
    finally:
        renderer.finish()


async def interactive_main(args: argparse.Namespace) -> int:
    runtime = build_runtime(args)
    workdir = runtime.config.working_directory
    session = new_session(workdir)
    verbose = args.verbose
    print_banner(args, runtime)

    while True:
        try:
            prompt = (await asyncio.to_thread(input, "\nYou> ")).strip()
        except EOFError:
            print("\nBye.")
            return 0
        except KeyboardInterrupt:
            print("\nInput cancelled.")
            continue

        if not prompt:
            continue

        command = prompt.lower()
        if command in {"/exit", "/quit", "exit", "quit"}:
            print("Bye.")
            return 0
        if command == "/help":
            print_help()
            continue
        if command in {"/new", "/clear"}:
            session = new_session(workdir)
            print("Started a new conversation.")
            continue
        if command == "/status":
            print_status(session, runtime, verbose)
            continue
        if command == "/verbose":
            verbose = not verbose
            print(f"Verbose mode {'enabled' if verbose else 'disabled'}.")
            continue

        try:
            await run_prompt(runtime, session, prompt, verbose)
        except KeyboardInterrupt:
            runtime.interrupt_controller.interrupt()
            print("\nRequest interrupted.")
            runtime.interrupt_controller.interrupted = False
            runtime.interrupt_controller.reason = "user"
        except Exception as exc:  # noqa: BLE001
            print(f"[error] {type(exc).__name__}: {exc}")


def main() -> int:
    args = parse_args()
    try:
        return asyncio.run(interactive_main(args))
    except KeyboardInterrupt:
        print("\nBye.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
