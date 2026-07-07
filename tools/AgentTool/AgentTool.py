from __future__ import annotations

import asyncio
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agentColorManager import setAgentColor
from .agentToolUtils import finalizeAgentTool, runAsyncAgentLifecycle
from .builtInAgents import getBuiltInAgents
from .built_in.generalPurposeAgent import GENERAL_PURPOSE_AGENT
from .constants import AGENT_TOOL_NAME, LEGACY_AGENT_TOOL_NAME
from .forkSubagent import (
    FORK_AGENT,
    buildForkedMessages,
    buildWorktreeNotice,
    isForkSubagentEnabled,
    isInForkChild,
)
from .loadAgentsDir import (
    AgentDefinition,
    AgentDefinitionsResult,
    filterAgentsByMcpRequirements,
    getAgentDefinitionsWithOverrides,
    hasRequiredMcpServers,
    isBuiltInAgent,
)
from .prompt import getPrompt
from .runAgent import getTaskOutputPath, runAgent
from .runtimeModels import (
    AppState,
    Message,
    ProgressMessage,
    Tool,
    ToolUseContext,
    ToolUseOptions,
    create_agent_id,
    create_progress_payload,
    create_user_message,
    ensure_directory,
    extract_text_content,
    pushd,
)


INPUT_SCHEMA = {
    "description": "short task description",
    "prompt": "task for the agent to perform",
    "subagent_type": "optional agent type",
    "model": "optional model override",
    "run_in_background": "optional background flag",
    "name": "optional teammate name",
    "team_name": "optional team name",
    "mode": "optional permission mode",
    "isolation": "optional isolation mode",
    "cwd": "optional working directory override",
}

OUTPUT_SCHEMA = {
    "completed": ["agentId", "agentType", "content", "usage", "totalToolUseCount", "totalDurationMs", "totalTokens"],
    "async_launched": ["agentId", "description", "prompt", "outputFile"],
    "remote_launched": ["taskId", "sessionUrl", "description", "prompt", "outputFile"],
    "teammate_spawned": ["teammate_id", "name", "description", "prompt"],
}


def _clock_ms() -> int:
    return int(time.time() * 1000)


def _query_source_for_agent(agent: AgentDefinition) -> str:
    source = "builtin" if isBuiltInAgent(agent) else "custom"
    return f"agent:{source}:{agent.agentType}"


def _default_tools() -> list[Tool]:
    names = [
        "Read",
        "Edit",
        "Write",
        "Bash",
        "PowerShell",
        "Glob",
        "Grep",
        "WebFetch",
        "WebSearch",
        AGENT_TOOL_NAME,
        "SendMessage",
        "TodoWrite",
    ]
    return [Tool(name=name, description=f"{name} tool") for name in names]


def _ensure_context(toolUseContext: ToolUseContext | None) -> ToolUseContext:
    if toolUseContext is not None:
        # 从当前目录中寻找agent配置文件
        if toolUseContext.options.agent_definitions is None:
            toolUseContext.options.agent_definitions = getAgentDefinitionsWithOverrides(str(Path.cwd()))
        # 配置Tool列表
        if not toolUseContext.options.tools:
            toolUseContext.options.tools = _default_tools()
        # options和app_states都会存agent定义，这边是做同步
        # options是本次调用，app_states是全局共享
        if toolUseContext.app_state.agent_definitions is None:
            toolUseContext.app_state.agent_definitions = toolUseContext.options.agent_definitions
        return toolUseContext
    definitions = getAgentDefinitionsWithOverrides(str(Path.cwd()))
    options = ToolUseOptions(tools=_default_tools(), agent_definitions=definitions)
    app_state = AppState(agent_definitions=definitions)
    return ToolUseContext(options=options, app_state=app_state)


def _select_agent(
    effective_type: str | None,   # agent类型名：planner,coder,research
    definitions: AgentDefinitionsResult,  # agent定义集合（至少包含activeagent或all agents）
    app_state: AppState,  # 应用状态，这边重点用到mcp_tools
    toolUseContext: ToolUseContext,
) -> tuple[AgentDefinition, bool]:  # 二元组，True表示走了默认fork agent，false表示从active agent找到
    # 未指定agent type时创建一个fork型agent去执行
    if effective_type is None:
        # 防止fork套fork:从来源字段判断+消息历史判断
        if toolUseContext.options.query_source == f"agent:builtin:{FORK_AGENT.agentType}" or isInForkChild(toolUseContext.messages):
            raise ValueError("Fork is not available inside a forked worker.")
        return FORK_AGENT, True
    # 获取active agents列表，没有的话用内置agent列表
    active = definitions.activeAgents or getBuiltInAgents()
    # next用法：在agent中找到第一个类型相符的，否则为None
    found = next((agent for agent in active if agent.agentType == effective_type), None)
    if found is None:
        available = ", ".join(agent.agentType for agent in active)
        # 抛出异常
        raise ValueError(f"Agent type '{effective_type}' not found. Available agents: {available}")
    # 检索是否依赖MCP服务，返回需要的MCP Server列表
    required = found.requiredMcpServers or []
    if required:
        """
        举例MCP Server名称
        mcp__github__search_repos
        mcp__filesystem__read_file
        mcp__browser__open_page
        返回["github","filesystem","browser"]
        """
        # 当前app_state包含的mcp server列表
        servers_with_tools = [
            tool.name.split("__")[1]
            for tool in app_state.mcp_tools
            if tool.name.startswith("mcp__") and "__" in tool.name
        ]
        # 判断是否包含必要的MCP服务
        if not hasRequiredMcpServers(found, servers_with_tools):
            # 判断pattern是否在servers_with_tools中，不在的话放入list
            # casefold():不区分大小写，大小写归一化
            missing = [pattern
                       for pattern in required 
                       if not any(pattern.casefold() in server.casefold() for server in servers_with_tools)
                       ]
            raise ValueError(
                f"Agent '{found.agentType}' requires MCP servers matching: {', '.join(missing)}"
            )
    return found, False

# 生成一个临时工作区，返回中座目录+git分支（None）
def _prepare_worktree(agent_id: str) -> dict[str, Any] | None:
    temp_dir = Path(tempfile.mkdtemp(prefix=f"agent-{agent_id[:8]}-"))
    return {"worktreePath": str(temp_dir), "worktreeBranch": None}


async def _cleanup_worktree(worktree_info: dict[str, Any] | None) -> dict[str, Any]:
    if not worktree_info:
        return {}
    worktree_path = Path(worktree_info["worktreePath"])
    try:
        # 若目录存在并且目录下面没有子文件/子目录，就删除它
        if worktree_path.exists() and not any(worktree_path.iterdir()):
            shutil.rmtree(worktree_path)
            return {}
    except OSError:
        return worktree_info
    return worktree_info


# 根据用户输入+上下文配置，选择合适的agent，以同步、异步、远程或worktree隔离方式启动它
@dataclass
class PythonAgentTool:
    name: str = AGENT_TOOL_NAME
    aliases: tuple[str, ...] = (LEGACY_AGENT_TOOL_NAME,)

    async def prompt(
        self,
        *,
        agents: list[AgentDefinition] | None = None,   # 可用的agent列表
        tools: list[Tool] | None = None,  # 工具列表
        getToolPermissionContext: Any = None,
        allowedAgentTypes: list[str] | None = None,
    ) -> str:
        del getToolPermissionContext  # 显示删除这个参数
        available_tools = tools or _default_tools()
        # 只关心mcp工具，mcp_github_search:github
        server_names = [
            tool.name.split("__")[1]
            for tool in available_tools
            if tool.name.startswith("mcp__") and "__" in tool.name
        ]
        # 只保留满足mcp功能的agents
        filtered = filterAgentsByMcpRequirements(agents or getBuiltInAgents(), server_names)
        return await getPrompt(filtered, False, allowedAgentTypes)

    async def description(self) -> str:
        return "Launch a new agent"

    # 执行Tool调用的入口
    async def call(
        self,
        *,
        prompt: str,  # 子agent的prompt
        description: str,  # 任务摘要、任务信息
        subagent_type: str | None = None, # 子agent类型
        model: str | None = None,
        run_in_background: bool | None = None,
        name: str | None = None,
        team_name: str | None = None,
        mode: str | None = None,
        isolation: str | None = None,
        cwd: str | None = None,  # 工作目录
        toolUseContext: ToolUseContext | None = None,
        canUseTool: Any = None,
        assistantMessage: Message | None = None,
        onProgress: Any = None,
    ) -> dict[str, Any]:
        del canUseTool, mode
        context = _ensure_context(toolUseContext)
        definitions: AgentDefinitionsResult = context.options.agent_definitions
        app_state = context.getAppState()
        if team_name and name:
            teammate_id = create_agent_id()
            app_state.tasks[teammate_id] = {
                "status": "spawned",  # 已生成
                "description": description,
                "team": team_name,
                "prompt": prompt,
            }
            return {
                "status": "teammate_spawned",
                "prompt": prompt,
                "teammate_id": teammate_id,
                "agent_id": teammate_id,
                "name": name,
                "team_name": team_name,
                "description": description,
            }
       
        # 若制定类型就使用；没有制定，并且fork子agent启用，设为None;否而设置为通用类型
        effective_type = subagent_type if subagent_type is not None else (None if isForkSubagentEnabled() else GENERAL_PURPOSE_AGENT.agentType)
        selected_agent, is_fork_path = _select_agent(effective_type, definitions, app_state, context)
        if selected_agent.color:
            setAgentColor(selected_agent.agentType, selected_agent.color)
        effective_isolation = isolation or selected_agent.isolation
        if effective_isolation == "remote":
            task_id = create_agent_id()
            output_file = getTaskOutputPath(task_id)
            Path(output_file).parent.mkdir(parents=True, exist_ok=True)
            Path(output_file).write_text(f"Remote agent placeholder for: {prompt}", encoding="utf-8")
            return {
                "status": "remote_launched",
                "taskId": task_id,
                "sessionUrl": f"https://remote.invalid/session/{task_id}",
                "description": description,
                "prompt": prompt,
                "outputFile": output_file,
            }
        early_agent_id = create_agent_id()
        worktree_info = _prepare_worktree(early_agent_id) if effective_isolation == "worktree" else None
        prompt_messages: list[Message]
        if is_fork_path and assistantMessage is not None:
            prompt_messages = buildForkedMessages(prompt, assistantMessage)
        else:
            prompt_messages = [create_user_message(prompt)]
        if is_fork_path and worktree_info:
            prompt_messages.append(
                create_user_message(
                    buildWorktreeNotice(str(Path.cwd()), worktree_info["worktreePath"])
                )
            )
        if onProgress and prompt_messages:
            onProgress(
                ProgressMessage(
                    data=create_progress_payload(prompt_messages[0], prompt, early_agent_id)
                )
            )
        metadata = {
            "prompt": prompt,
            "resolvedAgentModel": model or selected_agent.model or context.options.main_loop_model,
            "isBuiltInAgent": isBuiltInAgent(selected_agent),
            "startTime": _clock_ms(),
            "clock": _clock_ms,
            "agentType": selected_agent.agentType,
        }
        should_run_async = bool(run_in_background or selected_agent.background or isForkSubagentEnabled())
        working_dir = cwd or (worktree_info["worktreePath"] if worktree_info else None)
        if should_run_async:
            task_id = early_agent_id
            app_state.tasks[task_id] = {
                "status": "running",
                "description": description,
                "prompt": prompt,
                "messages": [],
                "agentType": selected_agent.agentType,
            }
            if name:
                app_state.agent_name_registry[name] = task_id
            with pushd(working_dir):
                asyncio.create_task(
                    runAsyncAgentLifecycle(
                        taskId=task_id,
                        abortController=context.abort_controller,
                        makeStream=lambda onCacheSafeParams: runAgent(
                            agentDefinition=selected_agent,
                            promptMessages=prompt_messages,
                            toolUseContext=context,
                            canUseTool=lambda _name: True,
                            isAsync=True,
                            querySource=_query_source_for_agent(selected_agent),
                            override={"agentId": task_id},
                            model=model,
                            availableTools=context.options.tools,
                            onCacheSafeParams=onCacheSafeParams,
                            worktreePath=worktree_info["worktreePath"] if worktree_info else None,
                            description=description,
                        ),
                        metadata=metadata,
                        description=description,
                        toolUseContext=context,
                        rootSetAppState=context.setAppStateForTasks,
                        agentIdForCleanup=task_id,
                        enableSummarization=False,
                        getWorktreeResult=lambda: _cleanup_worktree(worktree_info),
                        outputPath=getTaskOutputPath(task_id),
                    )
                )
            return {
                "status": "async_launched",
                "agentId": task_id,
                "description": description,
                "prompt": prompt,
                "outputFile": getTaskOutputPath(task_id),
                "canReadOutputFile": True,
            }
        agent_messages: list[Message] = []
        with pushd(working_dir):
            async for message in runAgent(
                agentDefinition=selected_agent,
                promptMessages=prompt_messages,
                toolUseContext=context,
                canUseTool=lambda _name: True,
                isAsync=False,
                querySource=_query_source_for_agent(selected_agent),
                override={"agentId": early_agent_id},
                model=model,
                availableTools=context.options.tools,
                worktreePath=worktree_info["worktreePath"] if worktree_info else None,
                description=description,
            ):
                agent_messages.append(message)
                if onProgress:
                    onProgress(
                        ProgressMessage(
                            data=create_progress_payload(message, prompt, early_agent_id)
                        )
                    )
        result = finalizeAgentTool(agent_messages, early_agent_id, metadata)
        worktree_result = await _cleanup_worktree(worktree_info)
        payload = {
            "status": "completed",
            "agentId": result.agentId,
            "agentType": result.agentType,
            "content": result.content,
            "totalToolUseCount": result.totalToolUseCount,
            "totalDurationMs": result.totalDurationMs,
            "totalTokens": result.totalTokens,
            "usage": result.usage,
            "prompt": prompt,
            **worktree_result,
        }
        Path(getTaskOutputPath(early_agent_id)).parent.mkdir(parents=True, exist_ok=True)
        Path(getTaskOutputPath(early_agent_id)).write_text(
            extract_text_content(result.content, "\n"), encoding="utf-8"
        )
        return payload

    def userFacingName(self, input_data: dict[str, Any] | None) -> str:
        if input_data and input_data.get("subagent_type") and input_data["subagent_type"] != GENERAL_PURPOSE_AGENT.agentType:
            return str(input_data["subagent_type"])
        return "Agent"


AgentTool = PythonAgentTool()

