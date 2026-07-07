from __future__ import annotations

from typing import Dict, Optional


AgentColorName = str

AGENT_COLORS: tuple[AgentColorName, ...] = (
    "red",
    "blue",
    "green",
    "yellow",
    "purple",
    "orange",
    "pink",
    "cyan",
)

AGENT_COLOR_TO_THEME_COLOR: dict[AgentColorName, str] = {
    "red": "red_for_subagents_only",
    "blue": "blue_for_subagents_only",
    "green": "green_for_subagents_only",
    "yellow": "yellow_for_subagents_only",
    "purple": "purple_for_subagents_only",
    "orange": "orange_for_subagents_only",
    "pink": "pink_for_subagents_only",
    "cyan": "cyan_for_subagents_only",
}

_agent_color_map: Dict[str, AgentColorName] = {}


def getAgentColor(agent_type: str) -> Optional[str]:
    if agent_type == "general-purpose":
        return None
    color = _agent_color_map.get(agent_type)
    if color in AGENT_COLOR_TO_THEME_COLOR:
        return AGENT_COLOR_TO_THEME_COLOR[color]
    return None


def setAgentColor(agent_type: str, color: AgentColorName | None) -> None:
    if not color:
        _agent_color_map.pop(agent_type, None)
        return
    if color in AGENT_COLORS:
        _agent_color_map[agent_type] = color

