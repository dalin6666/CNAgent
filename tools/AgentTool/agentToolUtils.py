from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from .constants import AGENT_TOOL_NAME, LEGACY_AGENT_TOOL_NAME
from .loadAgentsDir import AgentDefinition
from .runtimeModels import Message, Tool, ToolUseContext, count_tokens_from_usage, extract_text_content


ALL_AGENT_DISALLOWED_TOOLS = {AGENT_TOOL_NAME, LEGACY_AGENT_TOOL_NAME}
CUSTOM_AGENT_DISALLOWED_TOOLS = {"AskUserQuestion"}
ASYNC_AGENT_ALLOWED_TOOLS = {
    "Read",
    "Edit",
    "Write",
    "Bash",
    "PowerShell",
    "Glob",
    "Grep",
    "WebFetch",
    "WebSearch",
    "SendMessage",
    AGENT_TOOL_NAME,
    "TodoWrite",
    "LSP",
    "Config",
    "NotebookEdit",
    "Sleep",
}


@dataclass
class ResolvedAgentTools:
    hasWildcard: bool
    validTools: list[str]
    invalidTools: list[str]
    resolvedTools: list[Tool]
    allowedAgentTypes: list[str] | None = None


@dataclass
class AgentToolResult:
    agentId: str
    agentType: str | None
    content: list[dict[str, Any]]
    totalToolUseCount: int
    totalDurationMs: int
    totalTokens: int
    usage: dict[str, Any]


def _parse_tool_spec(spec: str) -> tuple[str, str | None]:
    if "(" not in spec or not spec.endswith(")"):
        return spec, None
    tool_name, raw = spec.split("(", 1)
    return tool_name, raw[:-1]


def filterToolsForAgent(
    *,
    tools: list[Tool],
    isBuiltIn: bool,
    isAsync: bool = False,
    permissionMode: str | None = None,
) -> list[Tool]:
    filtered: list[Tool] = []
    for tool in tools:
        if tool.name.startswith("mcp__"):
            filtered.append(tool)
            continue
        if permissionMode == "plan" and tool.name == "ExitPlanMode":
            filtered.append(tool)
            continue
        if tool.name in ALL_AGENT_DISALLOWED_TOOLS:
            continue
        if not isBuiltIn and tool.name in CUSTOM_AGENT_DISALLOWED_TOOLS:
            continue
        if isAsync and tool.name not in ASYNC_AGENT_ALLOWED_TOOLS:
            continue
        filtered.append(tool)
    return filtered


def resolveAgentTools(
    agentDefinition: AgentDefinition,
    availableTools: list[Tool],
    isAsync: bool = False,
    isMainThread: bool = False,
) -> ResolvedAgentTools:
    filtered_available = (
        availableTools
        if isMainThread
        else filterToolsForAgent(
            tools=availableTools,
            isBuiltIn=agentDefinition.source == "built-in",
            isAsync=isAsync,
            permissionMode=agentDefinition.permissionMode,
        )
    )
    disallowed = {
        _parse_tool_spec(spec)[0] for spec in (agentDefinition.disallowedTools or [])
    }
    allowed_available = [tool for tool in filtered_available if tool.name not in disallowed]
    specs = agentDefinition.tools
    if specs is None or specs == ["*"]:
        return ResolvedAgentTools(
            hasWildcard=True,
            validTools=[],
            invalidTools=[],
            resolvedTools=allowed_available,
        )
    by_name = {tool.name: tool for tool in allowed_available}
    valid: list[str] = []
    invalid: list[str] = []
    resolved: list[Tool] = []
    seen: set[str] = set()
    allowed_agent_types: list[str] | None = None
    for spec in specs:
        tool_name, rule_content = _parse_tool_spec(spec)
        if tool_name == AGENT_TOOL_NAME and rule_content:
            allowed_agent_types = [item.strip() for item in rule_content.split(",") if item.strip()]
        tool = by_name.get(tool_name)
        if tool is None:
            if tool_name == AGENT_TOOL_NAME and not isMainThread:
                valid.append(spec)
                continue
            invalid.append(spec)
            continue
        valid.append(spec)
        if tool.name not in seen:
            resolved.append(tool)
            seen.add(tool.name)
    return ResolvedAgentTools(
        hasWildcard=False,
        validTools=valid,
        invalidTools=invalid,
        resolvedTools=resolved,
        allowedAgentTypes=allowed_agent_types,
    )


def countToolUses(messages: list[Message]) -> int:
    count = 0
    for message in messages:
        if message.type != "assistant":
            continue
        count += sum(1 for block in message.content if block.get("type") == "tool_use")
    return count


def finalizeAgentTool(
    agentMessages: list[Message],
    agentId: str,
    metadata: dict[str, Any],
) -> AgentToolResult:
    last_assistant = next((message for message in reversed(agentMessages) if message.type == "assistant"), None)
    if last_assistant is None:
        raise ValueError("No assistant messages found")
    content = [block for block in last_assistant.content if block.get("type") == "text"]
    if not content:
        for message in reversed(agentMessages):
            if message.type != "assistant":
                continue
            text_blocks = [block for block in message.content if block.get("type") == "text"]
            if text_blocks:
                content = text_blocks
                break
    total_tokens = count_tokens_from_usage(last_assistant.usage)
    return AgentToolResult(
        agentId=agentId,
        agentType=metadata.get("agentType"),
        content=content,
        totalToolUseCount=countToolUses(agentMessages),
        totalDurationMs=int(metadata.get("now", metadata["clock"]()) - metadata["startTime"]),
        totalTokens=total_tokens,
        usage=last_assistant.usage,
    )


def getLastToolUseName(message: Message) -> str | None:
    if message.type != "assistant":
        return None
    for block in reversed(message.content):
        if block.get("type") == "tool_use":
            return str(block.get("name"))
    return None


def emitTaskProgress(
    tracker: dict[str, Any],
    taskId: str,
    toolUseId: str | None,
    description: str,
    startTime: int,
    lastToolName: str,
) -> dict[str, Any]:
    tracker["lastToolName"] = lastToolName
    tracker["toolUses"] = tracker.get("toolUses", 0) + 1
    tracker["description"] = description
    tracker["toolUseId"] = toolUseId
    tracker["startTime"] = startTime
    tracker["taskId"] = taskId
    return tracker


async def classifyHandoffIfNeeded(
    *,
    agentMessages: list[Message],
    tools: list[Tool],
    toolPermissionContext: Any,
    abortSignal: Any,
    subagentType: str,
    totalToolUseCount: int,
) -> str | None:
    del tools, toolPermissionContext, abortSignal, subagentType, totalToolUseCount
    final_text = extract_text_content(
        next((message.content for message in reversed(agentMessages) if message.type == "assistant"), []),
        "\n",
    )
    suspicious = ("rm -rf", "sudo ", "DROP TABLE", "curl | sh")
    if any(pattern in final_text for pattern in suspicious):
        return "SECURITY WARNING: review this sub-agent output carefully before acting on it."
    return None


def extractPartialResult(messages: list[Message]) -> str | None:
    for message in reversed(messages):
        if message.type != "assistant":
            continue
        text = extract_text_content(message.content, "\n")
        if text:
            return text
    return None


async def _maybe_await(value: Awaitable[Any] | Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value


async def runAsyncAgentLifecycle(
    *,
    taskId: str,
    abortController: Any,
    makeStream: Callable[[Callable[[dict[str, Any]], None] | None], Any],
    metadata: dict[str, Any],
    description: str,
    toolUseContext: ToolUseContext,
    rootSetAppState: Callable[[Any], None],
    agentIdForCleanup: str,
    enableSummarization: bool,
    getWorktreeResult: Callable[[], Awaitable[dict[str, Any]] | dict[str, Any]],
    outputPath: str | None = None,
) -> None:
    del enableSummarization, rootSetAppState, agentIdForCleanup
    agent_messages: list[Message] = []
    app_state = toolUseContext.getAppState()
    app_state.tasks[taskId] = {
        "status": "running",
        "description": description,
        "messages": [],
        "result": None,
    }
    tracker: dict[str, Any] = {"toolUses": 0, "tokens": 0}
    try:
        async for message in makeStream(None):
            agent_messages.append(message)
            app_state.tasks[taskId]["messages"].append(message)
            tracker["tokens"] += count_tokens_from_usage(message.usage)
            last_tool_name = getLastToolUseName(message)
            if last_tool_name:
                emitTaskProgress(
                    tracker,
                    taskId,
                    toolUseContext.tool_use_id,
                    description,
                    metadata["startTime"],
                    last_tool_name,
                )
        result = finalizeAgentTool(agent_messages, taskId, metadata)
        final_message = extract_text_content(result.content, "\n")
        warning = await classifyHandoffIfNeeded(
            agentMessages=agent_messages,
            tools=toolUseContext.options.tools,
            toolPermissionContext=app_state.tool_permission_context,
            abortSignal=abortController,
            subagentType=metadata.get("agentType", "agent"),
            totalToolUseCount=result.totalToolUseCount,
        )
        if warning:
            final_message = f"{warning}\n\n{final_message}"
        worktree_result = await _maybe_await(getWorktreeResult())
        app_state.tasks[taskId] = {
            **app_state.tasks[taskId],
            "status": "completed",
            "result": result,
            "finalMessage": final_message,
            **worktree_result,
        }
        if outputPath:
            Path(outputPath).parent.mkdir(parents=True, exist_ok=True)
            Path(outputPath).write_text(final_message or "", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        if getattr(abortController, "aborted", False):
            worktree_result = await _maybe_await(getWorktreeResult())
            partial = extractPartialResult(agent_messages)
            app_state.tasks[taskId] = {
                **app_state.tasks.get(taskId, {}),
                "status": "killed",
                "finalMessage": partial,
                **worktree_result,
            }
            if outputPath:
                Path(outputPath).parent.mkdir(parents=True, exist_ok=True)
                Path(outputPath).write_text(partial or "", encoding="utf-8")
            return
        worktree_result = await _maybe_await(getWorktreeResult())
        app_state.tasks[taskId] = {
            **app_state.tasks.get(taskId, {}),
            "status": "failed",
            "error": str(exc),
            **worktree_result,
        }
        if outputPath:
            Path(outputPath).parent.mkdir(parents=True, exist_ok=True)
            Path(outputPath).write_text(str(exc), encoding="utf-8")

