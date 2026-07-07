from __future__ import annotations

from ..constants import AGENT_TOOL_NAME
from ..loadAgentsDir import BuiltInAgentDefinition


def getPlanSystemPrompt(_: dict) -> str:
    return (
        "You are a software architect and planning specialist.\n\n"
        "This is a read-only planning task.\n"
        "- Do not modify files.\n"
        "- Explore the codebase, understand constraints, and design the solution.\n"
        "- End with a section named 'Critical Files for Implementation'."
    )


PLAN_AGENT = BuiltInAgentDefinition(
    agentType="Plan",
    whenToUse=(
        "Architect agent for planning implementation strategy, sequencing, and critical files."
    ),
    disallowedTools=[AGENT_TOOL_NAME, "ExitPlanMode", "FileEdit", "FileWrite", "NotebookEdit"],
    tools=["*"],
    model="inherit",
    omitClaudeMd=True,
    getSystemPrompt=getPlanSystemPrompt,
)

