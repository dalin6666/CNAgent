from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_runtime import RuntimeConfig, create_default_runtime
from agent_runtime.runtime.interruption import InterruptController
from agent_runtime.runtime.telemetry import TelemetryRecorder
from agent_runtime.schemas import SessionState
from agent_runtime.tools.base import ToolRuntimeContext


async def main() -> None:
    runtime = create_default_runtime(
        RuntimeConfig(
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
            }
        )
    )
    session = SessionState()
    session.metadata["working_directory"] = str(ROOT)
    telemetry = TelemetryRecorder(".agent_runtime_logs", session.session_id)
    context = ToolRuntimeContext(
        session=session,
        working_directory=str(ROOT),
        config=runtime.config,
        telemetry=telemetry,
        interrupt_controller=InterruptController(),
    )

    samples = [
        ("Read", {"file_path": "__init__.py", "offset": 1, "limit": 20}),
        ("Glob", {"pattern": "*.py", "path": str(ROOT)}),
        ("Grep", {"pattern": "AgentRuntime", "path": "agent_runtime", "output_mode": "files_with_matches"}),
        ("ToolSearch", {"query": "Tool"}),
        ("Bash", {"command": "echo legacy-adapter-ok"}),
        ("PowerShell", {"command": "Write-Output 'legacy-adapter-ok'"}),
        ("Config", {"setting": "model"}),
        ("MCP", {"server": "demo", "tool": "noop", "arguments": {}}),
        ("TaskCreate", {"subject": "smoke", "description": "hello"}),
        ("TaskList", {}),
        ("Agent", {"prompt": "Reply with a short sentence.", "description": "smoke-agent"}),
    ]

    for tool_name, arguments in samples:
        tool = runtime.tool_registry.require(tool_name)
        try:
            result = await tool.run(
                {"_tool_call_id": f"smoke-{tool_name}", **arguments},
                context,
            )
            print(f"[{tool_name}] error={result.is_error} summary={result.summary}")
        except Exception as exc:  # noqa: BLE001
            print(f"[{tool_name}] FAILED {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
