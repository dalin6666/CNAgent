from __future__ import annotations

from dataclasses import replace

from .loadAgentsDir import AgentDefinition


AGENT_SOURCE_GROUPS = [
    {"label": "User agents", "source": "userSettings"},
    {"label": "Project agents", "source": "projectSettings"},
    {"label": "Local agents", "source": "localSettings"},
    {"label": "Managed agents", "source": "policySettings"},
    {"label": "Plugin agents", "source": "plugin"},
    {"label": "CLI arg agents", "source": "flagSettings"},
    {"label": "Built-in agents", "source": "built-in"},
]


def resolveAgentOverrides(
    all_agents: list[AgentDefinition],
    active_agents: list[AgentDefinition],
) -> list[AgentDefinition]:
    active_map = {agent.agentType: agent for agent in active_agents}
    seen: set[tuple[str, str]] = set()
    resolved: list[AgentDefinition] = []
    for agent in all_agents:
        key = (agent.agentType, agent.source)
        if key in seen:
            continue
        seen.add(key)
        active = active_map.get(agent.agentType)
        overridden_by = active.source if active and active.source != agent.source else None
        resolved.append(replace(agent, overriddenBy=overridden_by))
    return resolved


def resolveAgentModelDisplay(agent: AgentDefinition) -> str | None:
    model = agent.model or "inherit"
    return model if model else None


def getOverrideSourceLabel(source: str) -> str:
    return source.replace("Settings", "").replace("-", " ").lower()


def compareAgentsByName(a: AgentDefinition, b: AgentDefinition) -> int:
    a_name = a.agentType.casefold()
    b_name = b.agentType.casefold()
    return (a_name > b_name) - (a_name < b_name)

