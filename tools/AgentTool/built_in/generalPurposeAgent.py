from __future__ import annotations

from ..loadAgentsDir import BuiltInAgentDefinition


def getGeneralPurposeSystemPrompt(_: dict) -> str:
    return (
        "You are an agent for Claude Code. Complete the delegated task fully.\n\n"
        "Strengths:\n"
        "- Search across codebases and configs\n"
        "- Analyze multiple files together\n"
        "- Investigate complex questions\n"
        "- Execute multi-step tasks\n\n"
        "Guidelines:\n"
        "- Search broadly before narrowing.\n"
        "- Prefer editing existing files over creating new ones.\n"
        "- Do not create documentation unless explicitly requested.\n"
        "- Respond with a concise report when finished."
    )


GENERAL_PURPOSE_AGENT = BuiltInAgentDefinition(
    agentType="general-purpose",
    whenToUse=(
        "General-purpose agent for researching complex questions, searching for code, "
        "and executing multi-step tasks."
    ),
    tools=["*"],
    getSystemPrompt=getGeneralPurposeSystemPrompt,
)

