from __future__ import annotations

import os

from .constants import AGENT_TOOL_NAME
from .forkSubagent import isForkSubagentEnabled
from .loadAgentsDir import AgentDefinition


def _get_tools_description(agent: AgentDefinition) -> str:
    allow = agent.tools or []
    deny = agent.disallowedTools or []
    if allow and deny:
        effective = [tool for tool in allow if tool not in set(deny)]
        return ", ".join(effective) if effective else "None"
    if allow:
        return ", ".join(allow)
    if deny:
        return f"All tools except {', '.join(deny)}"
    return "All tools"


def formatAgentLine(agent: AgentDefinition) -> str:
    return f"- {agent.agentType}: {agent.whenToUse} (Tools: {_get_tools_description(agent)})"


def shouldInjectAgentListInMessages() -> bool:
    value = os.environ.get("CLAUDE_CODE_AGENT_LIST_IN_MESSAGES")
    if value is None:
        return False
    return value in {"1", "true", "True"}


async def getPrompt(
    agent_definitions: list[AgentDefinition],
    isCoordinator: bool = False,
    allowedAgentTypes: list[str] | None = None,
) -> str:
    agents = (
        [agent for agent in agent_definitions if agent.agentType in allowedAgentTypes]
        if allowedAgentTypes
        else agent_definitions
    )
    agent_list = (
        "Available agent types are listed in system reminder messages."
        if shouldInjectAgentListInMessages()
        else "\n".join(formatAgentLine(agent) for agent in agents)
    )
    fork_enabled = isForkSubagentEnabled()
    shared = (
        f"Launch a new agent to handle complex multi-step tasks autonomously.\n\n"
        f"The {AGENT_TOOL_NAME} tool launches specialized agents that can work in parallel.\n\n"
        f"Available agent types:\n{agent_list}\n\n"
        + (
            f"When using {AGENT_TOOL_NAME}, specify subagent_type or omit it to fork yourself."
            if fork_enabled
            else f"When using {AGENT_TOOL_NAME}, specify subagent_type to choose an agent."
        )
    )
    if isCoordinator:
        return shared
    usage_notes = [
        "- Include a short description of the delegated task.",
        "- Give enough context that the agent can make informed decisions.",
        "- Tell the agent whether it should research or modify code.",
        "- Use background mode only when you can continue independently.",
        "- Reuse SendMessage-style continuation when the same agent should keep context.",
    ]
    if fork_enabled:
        usage_notes.extend(
            [
                "- Fork open-ended research when the intermediate tool output is not worth keeping.",
                "- Do not fabricate results for a fork that has not completed yet.",
                "- Write directive-style fork prompts because the child already inherits context.",
            ]
        )
    return f"{shared}\n\nUsage notes:\n" + "\n".join(usage_notes)
