from __future__ import annotations

import ast
import json
import os
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from .agentColorManager import AGENT_COLORS, AgentColorName, setAgentColor
from .agentMemory import AgentMemoryScope, loadAgentMemoryPrompt
from .agentMemorySnapshot import checkAgentMemorySnapshot, initializeFromSnapshot


SystemPromptFn = Callable[[dict[str, Any]], str]


@dataclass
class BaseAgentDefinition:
    agentType: str
    whenToUse: str  # 什么场景用
    getSystemPrompt: SystemPromptFn # 获取system_prompt函数
    source: str # 来源：builtin、custom、plugin
    tools: list[str] | None = None
    disallowedTools: list[str] | None = None # 禁止使用Tool列表
    skills: list[str] | None = None
    mcpServers: list[Any] | None = None
    """
    生命周期中额外逻辑：
    任务开始前、工具调用后、任务结束后
    {
    "beforeRun":function
    }
    
    """
    hooks: dict[str, Any] | None = None 
    color: AgentColorName | None = None
    model: str | None = None
    effort: Any = None  # 推理强度
    permissionMode: str | None = None # 权限模式
    maxTurns: int | None = None 
    filename: str | None = None
    baseDir: str | None = None  # 配置文件所在目录
    criticalSystemReminder_EXPERIMENTAL: str | None = None
    requiredMcpServers: list[str] | None = None
    background: bool = False # 是否可以作为后台agent运行，执行长期监听、异步处理等任务
    initialPrompt: str | None = None
    memory: AgentMemoryScope | None = None
    isolation: str | None = None # 隔离模式：独立的工作区、进程、隔离环境
    pendingSnapshotUpdate: dict[str, str] | None = None
    omitClaudeMd: bool = False # 是否忽略claude.md:存放agent指令、代码风格、项目结构等
    plugin: str | None = None
    callback: Callable[[], None] | None = None
    overriddenBy: str | None = None


@dataclass
class BuiltInAgentDefinition(BaseAgentDefinition):
    source: str = "built-in"
    baseDir: str = "built-in"


@dataclass
class CustomAgentDefinition(BaseAgentDefinition):
    pass


@dataclass
class PluginAgentDefinition(BaseAgentDefinition):
    source: str = "plugin"


AgentDefinition = BaseAgentDefinition


@dataclass
class AgentDefinitionsResult:
    activeAgents: list[AgentDefinition]
    allAgents: list[AgentDefinition]
    failedFiles: list[dict[str, str]] | None = None
    allowedAgentTypes: list[str] | None = None


def isBuiltInAgent(agent: AgentDefinition) -> bool:
    return agent.source == "built-in"


def isCustomAgent(agent: AgentDefinition) -> bool:
    return agent.source not in {"built-in", "plugin"}


def isPluginAgent(agent: AgentDefinition) -> bool:
    return agent.source == "plugin"


def getActiveAgentsFromList(all_agents: list[AgentDefinition]) -> list[AgentDefinition]:
    precedence = [
        [agent for agent in all_agents if agent.source == "built-in"],
        [agent for agent in all_agents if agent.source == "plugin"],
        [agent for agent in all_agents if agent.source == "userSettings"],
        [agent for agent in all_agents if agent.source == "projectSettings"],
        [agent for agent in all_agents if agent.source == "flagSettings"],
        [agent for agent in all_agents if agent.source == "policySettings"],
    ]
    selected: dict[str, AgentDefinition] = {}
    for group in precedence:
        for agent in group:
            selected[agent.agentType] = agent
    return list(selected.values())


def hasRequiredMcpServers(agent: AgentDefinition, available_servers: list[str]) -> bool:
    if not agent.requiredMcpServers:
        return True
    lowered = [server.casefold() for server in available_servers]
    return all(
        any(pattern.casefold() in server for server in lowered)
        for pattern in agent.requiredMcpServers
    )


def filterAgentsByMcpRequirements(
    agents: list[AgentDefinition], available_servers: list[str]
) -> list[AgentDefinition]:
    return [agent for agent in agents if hasRequiredMcpServers(agent, available_servers)]


def _is_auto_memory_enabled() -> bool:
    return os.environ.get("CLAUDE_CODE_ENABLE_AGENT_MEMORY", "1") not in {"0", "false", "False"}


def _initialize_agent_memory_snapshots(agents: list[CustomAgentDefinition]) -> None:
    for agent in agents:
        if agent.memory != "user":
            continue
        result = checkAgentMemorySnapshot(agent.agentType, agent.memory)
        if result.action == "initialize" and result.snapshotTimestamp:
            initializeFromSnapshot(agent.agentType, agent.memory, result.snapshotTimestamp)
        elif result.action == "prompt-update" and result.snapshotTimestamp:
            agent.pendingSnapshotUpdate = {"snapshotTimestamp": result.snapshotTimestamp}


def clearAgentDefinitionsCache() -> None:
    getAgentDefinitionsWithOverrides.cache_clear()


def _parse_scalar(value: str) -> Any:
    stripped = value.strip()
    if stripped in {"true", "false"}:
        return stripped == "true"
    if stripped.isdigit():
        return int(stripped)
    if stripped.startswith("[") or stripped.startswith("{") or stripped.startswith("("):
        try:
            return ast.literal_eval(stripped)
        except (ValueError, SyntaxError):
            return stripped
    if stripped.startswith('"') and stripped.endswith('"'):
        return stripped[1:-1]
    if stripped.startswith("'") and stripped.endswith("'"):
        return stripped[1:-1]
    return stripped


def parseFrontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    lines = text.splitlines()
    frontmatter_lines: list[str] = []
    body_index = 0
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            body_index = index + 1
            break
        frontmatter_lines.append(lines[index])
    data: dict[str, Any] = {}
    current_key: str | None = None
    current_list: list[Any] | None = None
    for raw_line in frontmatter_lines:
        if raw_line.startswith("  - ") and current_key is not None:
            if current_list is None:
                current_list = []
                data[current_key] = current_list
            current_list.append(_parse_scalar(raw_line[4:]))
            continue
        if ":" in raw_line:
            key, value = raw_line.split(":", 1)
            current_key = key.strip()
            current_list = None
            parsed = _parse_scalar(value)
            data[current_key] = parsed
    body = "\n".join(lines[body_index:])
    return data, body


def getParseError(frontmatter: dict[str, Any]) -> str:
    if not isinstance(frontmatter.get("name"), str) or not frontmatter.get("name"):
        return 'Missing required "name" field in frontmatter'
    if not isinstance(frontmatter.get("description"), str) or not frontmatter.get("description"):
        return 'Missing required "description" field in frontmatter'
    return "Unknown parsing error"


def _normalize_tool_specs(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(part).strip() for part in value if str(part).strip()]
    return None


def parseAgentFromJson(
    name: str, definition: Any, source: str = "flagSettings"
) -> CustomAgentDefinition | None:
    if not isinstance(definition, dict):
        return None
    description = definition.get("description")
    prompt = definition.get("prompt")
    if not isinstance(description, str) or not isinstance(prompt, str):
        return None
    tools = _normalize_tool_specs(definition.get("tools"))
    if _is_auto_memory_enabled() and definition.get("memory") and tools is not None:
        for tool_name in ["Write", "Edit", "Read"]:
            if tool_name not in tools:
                tools.append(tool_name)

    def system_prompt(_: dict[str, Any]) -> str:
        if _is_auto_memory_enabled() and definition.get("memory"):
            return f"{prompt}\n\n{loadAgentMemoryPrompt(name, definition['memory'])}"
        return prompt

    return CustomAgentDefinition(
        agentType=name,
        whenToUse=description,
        getSystemPrompt=system_prompt,
        source=source,
        tools=tools,
        disallowedTools=_normalize_tool_specs(definition.get("disallowedTools")),
        skills=_normalize_tool_specs(definition.get("skills")),
        mcpServers=definition.get("mcpServers"),
        hooks=definition.get("hooks") if isinstance(definition.get("hooks"), dict) else None,
        model=str(definition["model"]).strip() if definition.get("model") else None,
        effort=definition.get("effort"),
        permissionMode=definition.get("permissionMode"),
        maxTurns=int(definition["maxTurns"]) if definition.get("maxTurns") else None,
        initialPrompt=definition.get("initialPrompt"),
        background=bool(definition.get("background")),
        memory=definition.get("memory"),
        isolation=definition.get("isolation"),
    )


def parseAgentsFromJson(
    agents_json: Any, source: str = "flagSettings"
) -> list[AgentDefinition]:
    if not isinstance(agents_json, dict):
        return []
    parsed: list[AgentDefinition] = []
    for name, definition in agents_json.items():
        agent = parseAgentFromJson(str(name), definition, source)
        if agent is not None:
            parsed.append(agent)
    return parsed


def parseAgentFromMarkdown(
    filePath: str,
    baseDir: str,
    frontmatter: dict[str, Any],
    content: str,
    source: str,
) -> CustomAgentDefinition | None:
    agent_type = frontmatter.get("name")
    when_to_use = frontmatter.get("description")
    if not isinstance(agent_type, str) or not agent_type.strip():
        return None
    if not isinstance(when_to_use, str) or not when_to_use.strip():
        return None
    tools = _normalize_tool_specs(frontmatter.get("tools"))
    memory = frontmatter.get("memory")
    if _is_auto_memory_enabled() and memory and tools is not None:
        for tool_name in ["Write", "Edit", "Read"]:
            if tool_name not in tools:
                tools.append(tool_name)
    filename = Path(filePath).stem
    model_raw = frontmatter.get("model")
    color = frontmatter.get("color")
    parsed_color = color if color in AGENT_COLORS else None
    system_prompt = content.strip()

    def prompt(_: dict[str, Any]) -> str:
        if _is_auto_memory_enabled() and memory:
            return f"{system_prompt}\n\n{loadAgentMemoryPrompt(agent_type, memory)}"
        return system_prompt

    return CustomAgentDefinition(
        agentType=agent_type,
        whenToUse=when_to_use.replace("\\n", "\n"),
        getSystemPrompt=prompt,
        source=source,
        filename=filename,
        baseDir=baseDir,
        tools=tools,
        disallowedTools=_normalize_tool_specs(frontmatter.get("disallowedTools")),
        skills=_normalize_tool_specs(frontmatter.get("skills")),
        mcpServers=frontmatter.get("mcpServers") if isinstance(frontmatter.get("mcpServers"), list) else None,
        hooks=frontmatter.get("hooks") if isinstance(frontmatter.get("hooks"), dict) else None,
        color=parsed_color,
        model=str(model_raw).strip() if model_raw else None,
        effort=frontmatter.get("effort"),
        permissionMode=frontmatter.get("permissionMode"),
        maxTurns=int(frontmatter["maxTurns"]) if str(frontmatter.get("maxTurns", "")).isdigit() else None,
        background=bool(frontmatter.get("background")),
        initialPrompt=frontmatter.get("initialPrompt"),
        memory=memory if memory in {"user", "project", "local"} else None,
        isolation=frontmatter.get("isolation") if frontmatter.get("isolation") in {"worktree", "remote"} else None,
    )


def _load_custom_agents(cwd: str) -> tuple[list[CustomAgentDefinition], list[dict[str, str]]]:
    roots = [Path(cwd) / "agents", Path(cwd) / ".claude" / "agents"]
    agents: list[CustomAgentDefinition] = []
    failed: list[dict[str, str]] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix.lower() == ".md":
                frontmatter, body = parseFrontmatter(path.read_text(encoding="utf-8"))
                agent = parseAgentFromMarkdown(str(path), str(root), frontmatter, body, "projectSettings")
                if agent is None:
                    if frontmatter.get("name"):
                        failed.append({"path": str(path), "error": getParseError(frontmatter)})
                    continue
                agents.append(agent)
            elif path.suffix.lower() == ".json":
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    failed.append({"path": str(path), "error": str(exc)})
                    continue
                agents.extend(
                    agent for agent in parseAgentsFromJson(payload, "projectSettings") if agent is not None
                )
    return agents, failed

# 函数结果会被缓存，做多32组，若多次在同一cwd中调用，不需要重复加载agent文件
@lru_cache(maxsize=32)
def getAgentDefinitionsWithOverrides(cwd: str) -> AgentDefinitionsResult:
    # 简化模式下,把激活的agent、可用的agent全部设置成内置agent
    if os.environ.get("CLAUDE_CODE_SIMPLE") in {"1", "true", "True"}:
        from .builtInAgents import getBuiltInAgents
        #只加载内置agent
        builtins = getBuiltInAgents()
        return AgentDefinitionsResult(activeAgents=builtins, allAgents=builtins)
    from .builtInAgents import getBuiltInAgents

    # 从当前工作目录读取自定义agent,返回成功加载的自定义agent和失败的文件列表
    custom_agents, failed_files = _load_custom_agents(cwd)
    # 若自动记忆开启
    if _is_auto_memory_enabled():
        # 为自定义agent初始化memory,可能是对话状态、长期记忆、注入的一些预定义上下文
        _initialize_agent_memory_snapshots(custom_agents)
    # 获取自带的agents列表
    built_in_agents = getBuiltInAgents()
    all_agents = [*built_in_agents, *custom_agents]
    # 根据某些规则筛选出激活的agent列表（规则可能是配置文件开关、优先级、默认启用、用户覆盖设置）
    active_agents = getActiveAgentsFromList(all_agents)
    # 颜色是按照agent type注册的
    for agent in active_agents:
        if agent.color:
            setAgentColor(agent.agentType, agent.color)
    return AgentDefinitionsResult(
        activeAgents=active_agents,
        allAgents=all_agents,
        failedFiles=failed_files or None, # 若failedFiles是空列表，则设置为None
    )

