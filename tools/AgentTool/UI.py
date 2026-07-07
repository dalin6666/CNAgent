from __future__ import annotations

from typing import Any

from .AgentTool import INPUT_SCHEMA
from .agentColorManager import getAgentColor
from .built_in.generalPurposeAgent import GENERAL_PURPOSE_AGENT
from .runtimeModels import Message, ProgressMessage, Tool, extract_text_content


def AgentPromptDisplay(prompt: str, dim: bool = False) -> str:
    prefix = "Prompt" + (" (dim)" if dim else "")
    return f"{prefix}:\n{prompt}"


def AgentResponseDisplay(content: list[dict[str, Any]]) -> str:
    return "Response:\n" + extract_text_content(content, "\n")


def renderToolResultMessage(
    data: dict[str, Any],
    progressMessagesForMessage: list[ProgressMessage],
    *,
    tools: list[Tool],
    verbose: bool,
    theme: str = "default",
    isTranscriptMode: bool = False,
) -> str:
    del progressMessagesForMessage, tools, verbose, theme
    status = data.get("status")
    if status == "remote_launched":
        return f"Remote agent launched - taskId={data['taskId']} sessionUrl={data['sessionUrl']}"
    if status == "async_launched":
        body = "Backgrounded agent"
        if isTranscriptMode and data.get("prompt"):
            body += f"\n\n{AgentPromptDisplay(data['prompt'])}"
        return body
    if status != "completed":
        return ""
    summary = (
        f"Done ({data.get('totalToolUseCount', 0)} tool uses, "
        f"{data.get('totalTokens', 0)} tokens, {data.get('totalDurationMs', 0)} ms)"
    )
    if isTranscriptMode and data.get("content"):
        return f"{summary}\n\n{AgentResponseDisplay(data['content'])}"
    return summary


def renderToolUseMessage(*, description: str | None = None, prompt: str | None = None) -> str | None:
    del prompt
    return description


def renderToolUseTag(input: dict[str, Any]) -> str | None:
    model = input.get("model")
    if not model:
        return None
    return str(model)


def renderToolUseProgressMessage(
    progressMessages: list[ProgressMessage],
    *,
    tools: list[Tool],
    verbose: bool,
    terminalSize: dict[str, int] | None = None,
    inProgressToolCallCount: int | None = None,
    isTranscriptMode: bool = False,
) -> str:
    del tools, verbose, terminalSize, inProgressToolCallCount, isTranscriptMode
    if not progressMessages:
        return "Initializing..."
    latest = progressMessages[-1].data
    message = latest.get("message")
    if isinstance(message, Message):
        return extract_text_content(message.content, "\n") or "In progress..."
    return "In progress..."


def renderToolUseRejectedMessage(
    _input: dict[str, Any],
    *,
    progressMessagesForMessage: list[ProgressMessage],
    tools: list[Tool],
    verbose: bool,
    isTranscriptMode: bool = False,
) -> str:
    prefix = renderToolUseProgressMessage(
        progressMessagesForMessage,
        tools=tools,
        verbose=verbose,
        isTranscriptMode=isTranscriptMode,
    )
    return f"{prefix}\nRejected"


def renderToolUseErrorMessage(
    result: Any,
    *,
    progressMessagesForMessage: list[ProgressMessage],
    tools: list[Tool],
    verbose: bool,
    isTranscriptMode: bool = False,
) -> str:
    prefix = renderToolUseProgressMessage(
        progressMessagesForMessage,
        tools=tools,
        verbose=verbose,
        isTranscriptMode=isTranscriptMode,
    )
    return f"{prefix}\nError: {result}"


def userFacingName(input: dict[str, Any] | None) -> str:
    if input and input.get("subagent_type") and input["subagent_type"] != GENERAL_PURPOSE_AGENT.agentType:
        if input["subagent_type"] == "worker":
            return "Agent"
        return str(input["subagent_type"])
    return "Agent"


def userFacingNameBackgroundColor(input: dict[str, Any] | None) -> str | None:
    if not input or not input.get("subagent_type"):
        return None
    return getAgentColor(str(input["subagent_type"]))


def extractLastToolInfo(progressMessages: list[ProgressMessage], tools: list[Tool]) -> str | None:
    del tools
    for progress in reversed(progressMessages):
        payload = progress.data
        message = payload.get("message")
        if isinstance(message, Message):
            text = extract_text_content(message.content, "\n")
            if text:
                return text
    return None


def renderGroupedAgentToolUse(
    toolUses: list[dict[str, Any]],
    options: dict[str, Any],
) -> str:
    del options
    lines = []
    total = len(toolUses)
    unresolved = sum(1 for item in toolUses if not item.get("isResolved"))
    if unresolved:
        lines.append(f"Running {total} agents...")
    else:
        lines.append(f"{total} agents finished")
    for item in toolUses:
        parsed = item.get("param", {}).get("input", {})
        name = userFacingName(parsed if isinstance(parsed, dict) else None)
        description = parsed.get("description") if isinstance(parsed, dict) else None
        status = "error" if item.get("isError") else "done" if item.get("isResolved") else "running"
        lines.append(f"- {name}: {description or 'task'} [{status}]")
    return "\n".join(lines)


def inputSchema() -> dict[str, Any]:
    return INPUT_SCHEMA

