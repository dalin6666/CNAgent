from __future__ import annotations

import asyncio
import time
from typing import Any

from .agentToolUtils import runAsyncAgentLifecycle
from .built_in.generalPurposeAgent import GENERAL_PURPOSE_AGENT
from .forkSubagent import FORK_AGENT
from .loadAgentsDir import AgentDefinition
from .runAgent import getAgentTranscript, getTaskOutputPath, readAgentMetadata, runAgent
from .runtimeModels import ToolUseContext, create_user_message


async def resumeAgentBackground(
    *,
    agentId: str,
    prompt: str,
    toolUseContext: ToolUseContext,
    canUseTool: Any,
    invokingRequestId: str | None = None,
) -> dict[str, str]:
    del canUseTool, invokingRequestId
    transcript = getAgentTranscript(agentId)
    if transcript is None:
        raise ValueError(f"No transcript found for agent ID: {agentId}")
    meta = readAgentMetadata(agentId) or {}
    selected_agent: AgentDefinition = GENERAL_PURPOSE_AGENT
    if meta.get("agentType") == FORK_AGENT.agentType:
        selected_agent = FORK_AGENT
    else:
        definitions = getattr(toolUseContext.options.agent_definitions, "activeAgents", []) or []
        for agent in definitions:
            if agent.agentType == meta.get("agentType"):
                selected_agent = agent
                break
    description = meta.get("description") or "(resumed)"
    toolUseContext.getAppState().tasks[agentId] = {
        "status": "running",
        "description": description,
        "messages": list(transcript),
    }
    metadata = {
        "prompt": prompt,
        "resolvedAgentModel": selected_agent.model or toolUseContext.options.main_loop_model,
        "isBuiltInAgent": selected_agent.source == "built-in",
        "startTime": int(time.time() * 1000),
        "clock": lambda: int(time.time() * 1000),
        "agentType": selected_agent.agentType,
    }
    asyncio.create_task(
        runAsyncAgentLifecycle(
            taskId=agentId,
            abortController=toolUseContext.abort_controller,
            makeStream=lambda onCacheSafeParams: runAgent(
                agentDefinition=selected_agent,
                promptMessages=[*transcript, create_user_message(prompt)],
                toolUseContext=toolUseContext,
                canUseTool=lambda _name: True,
                isAsync=True,
                querySource=f"agent:resume:{selected_agent.agentType}",
                override={"agentId": agentId},
                availableTools=toolUseContext.options.tools,
                onCacheSafeParams=onCacheSafeParams,
                worktreePath=meta.get("worktreePath"),
                description=description,
            ),
            metadata=metadata,
            description=description,
            toolUseContext=toolUseContext,
            rootSetAppState=toolUseContext.setAppStateForTasks,
            agentIdForCleanup=agentId,
            enableSummarization=False,
            getWorktreeResult=lambda: {"worktreePath": meta.get("worktreePath")} if meta.get("worktreePath") else {},
            outputPath=getTaskOutputPath(agentId),
        )
    )
    return {
        "agentId": agentId,
        "description": description,
        "outputFile": getTaskOutputPath(agentId),
    }

