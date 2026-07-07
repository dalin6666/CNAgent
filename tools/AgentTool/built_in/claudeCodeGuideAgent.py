from __future__ import annotations

from ..loadAgentsDir import BuiltInAgentDefinition


CLAUDE_CODE_GUIDE_AGENT_TYPE = "claude-code-guide"


def getClaudeCodeGuidePrompt(_: dict) -> str:
    return (
        "You are the Claude guide agent.\n\n"
        "Domains:\n"
        "1. Claude Code CLI\n"
        "2. Claude Agent SDK\n"
        "3. Claude API\n\n"
        "Approach:\n"
        "- Prefer official documentation.\n"
        "- Fetch relevant docs and cite concrete URLs when possible.\n"
        "- Keep answers concise and actionable.\n"
        "- Mention related commands or features when helpful."
    )


CLAUDE_CODE_GUIDE_AGENT = BuiltInAgentDefinition(
    agentType=CLAUDE_CODE_GUIDE_AGENT_TYPE,
    whenToUse=(
        "Use this agent for questions about Claude Code, the Agent SDK, or the Claude API."
    ),
    tools=["Glob", "Grep", "Read", "WebFetch", "WebSearch"],
    model="haiku",
    permissionMode="dontAsk",
    getSystemPrompt=getClaudeCodeGuidePrompt,
)

