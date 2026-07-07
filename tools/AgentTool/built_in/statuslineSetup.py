from __future__ import annotations

from ..loadAgentsDir import BuiltInAgentDefinition


STATUSLINE_SYSTEM_PROMPT = """
You are a status line setup agent.

Responsibilities:
- Read the user's shell prompt configuration.
- Translate PS1-style prompts into a Claude Code statusLine command.
- Update ~/.claude/settings.json without clobbering unrelated settings.
- Summarize what changed and remind the parent that future status-line edits should reuse this agent.

Guidelines:
- Preserve colors if they exist.
- Remove trailing prompt symbols such as '$' or '>'.
- If a longer script is needed, place it under ~/.claude and reference it from settings.
""".strip()


STATUSLINE_SETUP_AGENT = BuiltInAgentDefinition(
    agentType="statusline-setup",
    whenToUse="Use this agent to configure the Claude Code status line.",
    tools=["Read", "Edit"],
    model="sonnet",
    color="orange",
    getSystemPrompt=lambda _: STATUSLINE_SYSTEM_PROMPT,
)

