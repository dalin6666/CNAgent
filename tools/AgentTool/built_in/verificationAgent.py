from __future__ import annotations

from ..constants import AGENT_TOOL_NAME
from ..loadAgentsDir import BuiltInAgentDefinition


VERIFICATION_SYSTEM_PROMPT = """
You are a verification specialist. Your job is to try to break the implementation.

Core rules:
- Do not modify the project.
- Run builds, tests, and realistic checks rather than relying on code reading alone.
- Always include exact commands, observed output, and a PASS/FAIL/PARTIAL result per check.
- End with exactly one line: VERDICT: PASS, VERDICT: FAIL, or VERDICT: PARTIAL.
""".strip()


VERIFICATION_AGENT = BuiltInAgentDefinition(
    agentType="verification",
    whenToUse=(
        "Use this agent to verify implementation work after non-trivial changes."
    ),
    color="red",
    background=True,
    model="inherit",
    disallowedTools=[AGENT_TOOL_NAME, "ExitPlanMode", "FileEdit", "FileWrite", "NotebookEdit"],
    criticalSystemReminder_EXPERIMENTAL=(
        "CRITICAL: verification-only task. Do not edit project files. End with VERDICT: PASS, FAIL, or PARTIAL."
    ),
    getSystemPrompt=lambda _: VERIFICATION_SYSTEM_PROMPT,
)

