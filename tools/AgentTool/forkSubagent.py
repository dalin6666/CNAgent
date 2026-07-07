from __future__ import annotations

import os
from copy import deepcopy

from .loadAgentsDir import BuiltInAgentDefinition
from .runtimeModels import Message, create_user_message


FORK_BOILERPLATE_TAG = "forked-worker"
FORK_DIRECTIVE_PREFIX = "Directive: "
FORK_SUBAGENT_TYPE = "fork"


def isForkSubagentEnabled() -> bool:
    return os.environ.get("CLAUDE_CODE_ENABLE_FORK_SUBAGENT", "0") in {"1", "true", "True"}


FORK_AGENT = BuiltInAgentDefinition(
    agentType=FORK_SUBAGENT_TYPE,
    whenToUse=(
        "Implicit fork that inherits the parent conversation context. "
        "Triggered by omitting subagent_type while fork support is enabled."
    ),
    tools=["*"],
    maxTurns=200,
    model="inherit",
    permissionMode="bubble",
    getSystemPrompt=lambda _: "",
)


def isInForkChild(messages: list[Message]) -> bool:
    for message in messages:
        if message.type != "user":
            continue
        for block in message.content:
            if block.get("type") == "text" and f"<{FORK_BOILERPLATE_TAG}>" in str(block.get("text", "")):
                return True
    return False


FORK_PLACEHOLDER_RESULT = "Fork started - processing in background"


def buildChildMessage(directive: str) -> str:
    return (
        f"<{FORK_BOILERPLATE_TAG}>\n"
        "STOP. READ THIS FIRST.\n\n"
        "You are a forked worker process. Execute directly; do not spawn more sub-agents.\n"
        "Do not converse or narrate. Use tools, then report once.\n"
        "Your response must begin with 'Scope:'.\n"
        f"</{FORK_BOILERPLATE_TAG}>\n\n"
        f"{FORK_DIRECTIVE_PREFIX}{directive}"
    )


def buildForkedMessages(directive: str, assistant_message: Message) -> list[Message]:
    full_assistant = deepcopy(assistant_message)
    tool_results = []
    for block in assistant_message.content:
        if block.get("type") == "tool_use":
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.get("id"),
                    "content": [{"type": "text", "text": FORK_PLACEHOLDER_RESULT}],
                }
            )
    if not tool_results:
        return [create_user_message(buildChildMessage(directive))]
    tool_results.append({"type": "text", "text": buildChildMessage(directive)})
    return [full_assistant, create_user_message(tool_results)]


def buildWorktreeNotice(parent_cwd: str, worktree_cwd: str) -> str:
    return (
        f"You inherited context from {parent_cwd} but you are operating in isolated worktree "
        f"{worktree_cwd}. Translate paths accordingly and re-read files before editing."
    )

