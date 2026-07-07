# Agent Runtime Skeleton

This package contains a Python skeleton for a Claude-like agent runtime.

## Directory Tree

```text
agent_runtime/
  __init__.py
  README.md
  config.py
  errors.py
  events.py
  schemas.py
  providers/
    __init__.py
    base.py
    mock_provider.py
    openai_compatible.py
  runtime/
    __init__.py
    attachments.py
    budget.py
    compression.py
    engine.py
    fallback.py
    hooks.py
    interruption.py
    mcp.py
    memory.py
    skills.py
    telemetry.py
  tools/
    __init__.py
    base.py
    builtin_echo.py
    builtin_glob_search.py
    builtin_read_file.py
    legacy_adapter.py
    permissions.py
    registry.py
```

## Capability Mapping

1. Main loop orchestration: `runtime/engine.py`
2. Multi-turn reasoning: `runtime/engine.py`
3. Tool call and result injection: `runtime/engine.py`, `tools/registry.py`
4. Streaming output and streaming tools: `providers/mock_provider.py`, `tools/base.py`
5. Context trimming, folding, compression: `runtime/compression.py`
6. Prompt-too-long recovery: `runtime/engine.py`
7. Max-output continuation: `runtime/engine.py`
8. Model fallback: `runtime/fallback.py`
9. Tool permission control: `tools/permissions.py`
10. Stop hooks: `runtime/hooks.py`
11. User interruption: `runtime/interruption.py`
12. Attachment and file-change injection: `runtime/attachments.py`
13. Memory prefetch: `runtime/memory.py`
14. Skill prefetch: `runtime/skills.py`
15. Dynamic MCP tool registration: `runtime/mcp.py`
16. Token budget management: `runtime/budget.py`
17. Max turn limit: `runtime/engine.py`
18. Logging and telemetry: `runtime/telemetry.py`

## Legacy Tool Adaptation

Top-level legacy tools from `D:/code_project/python_port/tools` are adapted through
`tools/legacy_adapter.py`.

- Preserves legacy tool names such as `Read`, `Glob`, `Bash`, `Agent`
- Bridges to legacy `ToolUseContext` implementations
- Carries aliases, schema metadata, read-only hints, and interaction hints
- Converts legacy permission decisions into runtime-compatible permission behavior

## Real Model Providers

The runtime now supports OpenAI-compatible Chat Completions providers through
`providers/openai_compatible.py`.

- OpenAI / GPT via `openai_provider_config(...)`
- DeepSeek via `deepseek_provider_config(...)`
- Qwen via `qwen_provider_config(...)`

Provider setup examples are documented in
`D:/code_project/python_port/AGENT_PROVIDER_SETUP.md`.

## Interactive Command Line

Install the runtime dependency:

```powershell
python -m pip install -r requirements.txt
```

Configure your DeepSeek API key and start the command-line interface:

```powershell
$env:DEEPSEEK_API_KEY = "sk-..."
python examples\run_cli_agent.py
```

DeepSeek is the default provider and uses `deepseek-v4-flash`. You can also set
the provider and model explicitly:

```powershell
$env:AGENT_PROVIDER = "deepseek"
$env:DEEPSEEK_API_KEY = "sk-..."
$env:AGENT_MODEL = "deepseek-v4-flash"
python examples\run_cli_agent.py
```

To run locally without an API key, select the built-in mock provider explicitly:

```powershell
python examples\run_cli_agent.py --provider mock
```

The CLI is a presentation layer over the existing `AgentRuntime.stream()` API.
It keeps the same runtime, provider, tool, permission, context, and telemetry
logic. Available commands are `/help`, `/new`, `/status`, `/verbose`, and
`/exit`.
