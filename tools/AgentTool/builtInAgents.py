from __future__ import annotations

import os

from .built_in.claudeCodeGuideAgent import CLAUDE_CODE_GUIDE_AGENT
from .built_in.exploreAgent import EXPLORE_AGENT
from .built_in.generalPurposeAgent import GENERAL_PURPOSE_AGENT
from .built_in.planAgent import PLAN_AGENT
from .built_in.statuslineSetup import STATUSLINE_SETUP_AGENT
from .built_in.verificationAgent import VERIFICATION_AGENT
from .loadAgentsDir import AgentDefinition


def areExplorePlanAgentsEnabled() -> bool:
    return os.environ.get("CLAUDE_CODE_ENABLE_EXPLORE_PLAN_AGENTS", "1") not in {"0", "false", "False"}


def getBuiltInAgents() -> list[AgentDefinition]:
    if os.environ.get("CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS") in {"1", "true", "True"}:
        return []
    agents: list[AgentDefinition] = [GENERAL_PURPOSE_AGENT, STATUSLINE_SETUP_AGENT]
    if areExplorePlanAgentsEnabled():
        agents.extend([EXPLORE_AGENT, PLAN_AGENT])
    if os.environ.get("CLAUDE_CODE_ENTRYPOINT") not in {"sdk-ts", "sdk-py", "sdk-cli"}:
        agents.append(CLAUDE_CODE_GUIDE_AGENT)
    if os.environ.get("CLAUDE_CODE_ENABLE_VERIFICATION_AGENT") in {"1", "true", "True"}:
        agents.append(VERIFICATION_AGENT)
    return agents

