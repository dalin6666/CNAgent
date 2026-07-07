from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, AsyncGenerator, Callable

from .agentToolUtils import resolveAgentTools
from .loadAgentsDir import AgentDefinition
from .runtimeModels import (
    AppState,
    Message,
    Tool,
    ToolUseContext,
    ToolUseOptions,
    create_agent_id,
    create_user_message,
    default_query_runner,
    ensure_directory,
    extract_text_content,
)


def _runtime_root() -> Path:
    return ensure_directory(Path.cwd() / ".python_agent_runtime")


def _transcript_path(agent_id: str) -> Path:
    return ensure_directory(_runtime_root() / "transcripts") / f"{agent_id}.json"


def _metadata_path(agent_id: str) -> Path:
    return ensure_directory(_runtime_root() / "metadata") / f"{agent_id}.json"


def getTaskOutputPath(agent_id: str) -> str:
    return str(ensure_directory(_runtime_root() / "task_output") / f"{agent_id}.txt")


def _message_to_json(message: Message) -> dict[str, Any]:
    return {
        "type": message.type,
        "content": message.content,
        "uuid": message.uuid,
        "usage": message.usage,
        "request_id": message.request_id,
        "subtype": message.subtype,
        "prompt": message.prompt,
        "tool_use_result": message.tool_use_result,
        "is_meta": message.is_meta,
    }


def _message_from_json(payload: dict[str, Any]) -> Message:
    return Message(
        type=payload["type"],
        content=payload.get("content", []),
        uuid=payload.get("uuid"),
        usage=payload.get("usage", {}),
        request_id=payload.get("request_id"),
        subtype=payload.get("subtype"),
        prompt=payload.get("prompt"),
        tool_use_result=payload.get("tool_use_result"),
        is_meta=payload.get("is_meta", False),
    )


def recordSidechainTranscript(messages: list[Message], agent_id: str) -> None:
    path = _transcript_path(agent_id)
    current = []
    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
    current.extend(_message_to_json(message) for message in messages)
    path.write_text(json.dumps(current, indent=2), encoding="utf-8")


def writeAgentMetadata(agent_id: str, payload: dict[str, Any]) -> None:
    _metadata_path(agent_id).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def readAgentMetadata(agent_id: str) -> dict[str, Any] | None:
    path = _metadata_path(agent_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def getAgentTranscript(agent_id: str) -> list[Message] | None:
    path = _transcript_path(agent_id)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [_message_from_json(item) for item in payload]


def filterIncompleteToolCalls(messages: list[Message]) -> list[Message]:
    resolved_tool_ids: set[str] = set()
    for message in messages:
        if message.type != "user":
            continue
        for block in message.content:
            if block.get("type") == "tool_result":
                resolved_tool_ids.add(str(block.get("tool_use_id")))
    filtered: list[Message] = []
    for message in messages:
        if message.type != "assistant":
            filtered.append(message)
            continue
        incomplete = any(
            block.get("type") == "tool_use" and str(block.get("id")) not in resolved_tool_ids
            for block in message.content
        )
        if not incomplete:
            filtered.append(message)
    return filtered


async def getAgentSystemPrompt(
    agentDefinition: AgentDefinition,
    toolUseContext: ToolUseContext,
    resolvedAgentModel: str,
    additionalWorkingDirectories: list[str],
    resolvedTools: list[Tool],
) -> list[str]:
    enabled = ", ".join(tool.name for tool in resolvedTools)
    try:
        base = agentDefinition.getSystemPrompt({"toolUseContext": toolUseContext})
    except Exception:  # noqa: BLE001
        base = "You are a helpful agent."
    env_note = (
        f"Model: {resolvedAgentModel}\n"
        f"Working directories: {', '.join(additionalWorkingDirectories) or str(Path.cwd())}\n"
        f"Enabled tools: {enabled or 'none'}"
    )
    return [base, env_note]


def _query_runner(tool_use_context: ToolUseContext):
    return tool_use_context.options.query_runner or default_query_runner


async def runAgent(
    *,
    agentDefinition: AgentDefinition,
    promptMessages: list[Message],
    toolUseContext: ToolUseContext,
    canUseTool: Callable[[str], bool] | None,
    isAsync: bool,
    canShowPermissionPrompts: bool | None = None,
    forkContextMessages: list[Message] | None = None,
    querySource: str,
    override: dict[str, Any] | None = None,
    model: str | None = None,
    maxTurns: int | None = None,
    preserveToolUseResults: bool = False,
    availableTools: list[Tool] | None = None,
    allowedTools: list[str] | None = None,
    onCacheSafeParams: Callable[[dict[str, Any]], None] | None = None,
    contentReplacementState: dict[str, Any] | None = None,
    useExactTools: bool = False,
    worktreePath: str | None = None,
    description: str | None = None,
    transcriptSubdir: str | None = None,
    onQueryProgress: Callable[[], None] | None = None,
) -> AsyncGenerator[Message, None]:
    del canUseTool, canShowPermissionPrompts, preserveToolUseResults, contentReplacementState, transcriptSubdir
    app_state: AppState = toolUseContext.getAppState()
    agent_id = (override or {}).get("agentId") or create_agent_id()
    context_messages = filterIncompleteToolCalls(forkContextMessages or [])
    initial_messages = [*context_messages, *promptMessages]
    worker_tools = availableTools or toolUseContext.options.tools
    resolved_tools = (
        worker_tools
        if useExactTools
        else resolveAgentTools(agentDefinition, worker_tools, isAsync=isAsync).resolvedTools
    )
    resolved_model = model or agentDefinition.model or toolUseContext.options.main_loop_model
    additional_dirs = list(app_state.tool_permission_context.additional_working_directories.keys())
    system_prompt_parts = (
        [override["systemPrompt"]]
        if override and override.get("systemPrompt")
        else await getAgentSystemPrompt(
            agentDefinition,
            toolUseContext,
            resolved_model,
            additional_dirs,
            resolved_tools,
        )
    )
    agent_options = ToolUseOptions(
        tools=resolved_tools,
        main_loop_model=resolved_model,
        mcp_clients=toolUseContext.options.mcp_clients,
        mcp_resources=toolUseContext.options.mcp_resources,
        agent_definitions=toolUseContext.options.agent_definitions,
        custom_system_prompt=toolUseContext.options.custom_system_prompt,
        append_system_prompt=toolUseContext.options.append_system_prompt,
        query_source=querySource,
        commands=toolUseContext.options.commands,
        verbose=toolUseContext.options.verbose,
        debug=toolUseContext.options.debug,
        is_non_interactive_session=isAsync or toolUseContext.options.is_non_interactive_session,
        thinking_config=(
            toolUseContext.options.thinking_config if useExactTools else {"type": "disabled"}
        ),
        query_runner=toolUseContext.options.query_runner,
    )
    if allowedTools:
        agent_options.tools = [tool for tool in agent_options.tools if tool.name in allowedTools]
    agent_context = ToolUseContext(
        options=agent_options,
        messages=list(initial_messages),
        app_state=app_state,
        tool_use_id=toolUseContext.tool_use_id,
        agent_id=agent_id,
        rendered_system_prompt="\n\n".join(system_prompt_parts),
        abort_controller=(override or {}).get("abortController", toolUseContext.abort_controller),
    )
    if agentDefinition.initialPrompt:
        agent_context.messages.insert(0, create_user_message(agentDefinition.initialPrompt, is_meta=True))
    if agentDefinition.skills:
        for skill in agentDefinition.skills:
            agent_context.messages.append(
                create_user_message(f"Preloaded skill: {skill}", is_meta=True)
            )
    if onCacheSafeParams:
        onCacheSafeParams(
            {
                "systemPrompt": "\n\n".join(system_prompt_parts),
                "userContext": {"cwd": worktreePath or str(Path.cwd())},
                "systemContext": {"querySource": querySource},
                "toolUseContext": agent_context,
                "forkContextMessages": initial_messages,
            }
        )
    recordSidechainTranscript(initial_messages, agent_id)
    writeAgentMetadata(
        agent_id,
        {
            "agentType": agentDefinition.agentType,
            "worktreePath": worktreePath,
            "description": description,
        },
    )
    runner = _query_runner(agent_context)
    async for message in runner(
        messages=agent_context.messages,
        system_prompt="\n\n".join(system_prompt_parts),
        user_context={"cwd": worktreePath or str(Path.cwd())},
        system_context={"querySource": querySource},
        tool_use_context=agent_context,
        query_source=querySource,
        max_turns=maxTurns or agentDefinition.maxTurns,
    ):
        if onQueryProgress:
            onQueryProgress()
        recordSidechainTranscript([message], agent_id)
        yield message
    if agentDefinition.callback:
        agentDefinition.callback()
    app_state.todos.pop(agent_id, None)
    output_path = Path(getTaskOutputPath(agent_id))
    if not output_path.exists():
        final_text = extract_text_content(
            next((message.content for message in reversed(getAgentTranscript(agent_id) or []) if message.type == "assistant"), []),
            "\n",
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(final_text, encoding="utf-8")

