from __future__ import annotations

from ..constants import AGENT_TOOL_NAME
from ..loadAgentsDir import BuiltInAgentDefinition


EXPLORE_AGENT_MIN_QUERIES = 3


def getExploreSystemPrompt(_: dict) -> str:
    return (
        "You are a read-only file search specialist.\n\n"
        "Rules:\n"
        "- Never create, edit, move, or delete files.\n"
        "- Only use read-only inspection tools.\n"
        "- Prefer fast search strategies first, then targeted reads.\n"
        "- Return findings directly; do not generate files.\n\n"
        "Strengths:\n"
        "- Finding files via patterns\n"
        "- Searching content with regex\n"
        "- Reading and summarizing relevant code quickly"
    )


EXPLORE_AGENT = BuiltInAgentDefinition(
    agentType="Explore",
    whenToUse=(
        "Fast agent specialized for exploring codebases, locating files, "
        "and answering read-only codebase questions."
    ),
    disallowedTools=[AGENT_TOOL_NAME, "ExitPlanMode", "FileEdit", "FileWrite", "NotebookEdit"],
    model="haiku",
    omitClaudeMd=True,
    getSystemPrompt=getExploreSystemPrompt,
)

