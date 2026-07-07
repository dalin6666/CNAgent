from __future__ import annotations

import asyncio
import contextlib
import os
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Iterable, List, Optional


def default_usage() -> dict[str, Any]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "server_tool_use": None,
        "service_tier": None,
        "cache_creation": None,
    }


def _coerce_blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [deepcopy(block) for block in content]
    return [{"type": "text", "text": str(content)}]


@dataclass
class Message:
    type: str
    content: list[dict[str, Any]]
    uuid: str = field(default_factory=lambda: uuid.uuid4().hex)
    usage: dict[str, Any] = field(default_factory=default_usage)
    request_id: str | None = None
    subtype: str | None = None
    prompt: str | None = None
    tool_use_result: Any = None
    is_meta: bool = False


@dataclass
class ProgressMessage:
    data: dict[str, Any]
    uuid: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class Tool:
    name: str
    description: str = ""
    # default_factory=dict:新建一个空dict作为默认值
    input_schema: dict[str, Any] = field(default_factory=dict)
    user_facing_name_fn: Callable[[Any], str] | None = None
    tool_use_summary_fn: Callable[[Any], str | None] | None = None

    def userFacingName(self, parsed_input: Any = None) -> str:
        if self.user_facing_name_fn:
            return self.user_facing_name_fn(parsed_input)
        return self.name

    def getToolUseSummary(self, parsed_input: Any = None) -> str | None:
        if self.tool_use_summary_fn:
            return self.tool_use_summary_fn(parsed_input)
        return None


@dataclass
class AbortController:
    _aborted: bool = False

    def abort(self) -> None:
        self._aborted = True

    @property
    def signal(self) -> "AbortController":
        return self

    @property
    def aborted(self) -> bool:
        return self._aborted


@dataclass
class ToolPermissionContext:
    mode: str = "acceptEdits"
    additional_working_directories: dict[str, bool] = field(default_factory=dict)
    always_allow_rules: dict[str, list[str]] = field(
        default_factory=lambda: {"cliArg": [], "session": []}
    )
    should_avoid_permission_prompts: bool = False
    await_automated_checks_before_dialog: bool = False


@dataclass
class AppState:
    # tool调用权限中心：哪些tool允许调用/需要确认/,是否允许写文件、执行命令、联网，会话权限
    tool_permission_context: ToolPermissionContext = field(
        default_factory=ToolPermissionContext
    )
    mcp_tools: list[Tool] = field(default_factory=list)
    mcp_clients: list[dict[str, Any]] = field(default_factory=list)
    # 
    tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
    agent_name_registry: dict[str, str] = field(default_factory=dict)
    agent: str | None = None
    agent_definitions: Any = None
    todos: dict[str, list[Any]] = field(default_factory=dict)
    kairos_enabled: bool = False
    effort_value: Any = None


@dataclass
class ToolUseOptions:
    tools: list[Tool] = field(default_factory=list)
    # 主循环Model name
    main_loop_model: str = "sonnet"
    mcp_clients: list[dict[str, Any]] = field(default_factory=list)
    mcp_resources: list[dict[str, Any]] = field(default_factory=list)
    # 多agent中 存放子agent配置、prompt模板、能力边界、路由规则
    agent_definitions: Any = None
    custom_system_prompt: str | None = None
    append_system_prompt: str | None = None
    # query来源：用户输入、自动任务、文件系统、外部接口、某个子agent
    query_source: str | None = None
    # 可执行配置列表：每个包含命令名称、参数、描述、绑定函数、是否启用
    commands: list[dict[str, Any]] = field(default_factory=list)
    # 是否输出详细信息
    verbose: bool = False
    # 是否调试
    debug: bool = False
    # 是否交互式对话
    is_non_interactive_session: bool = False
    # thinking配置：是否开启思考、思考类型、思考深度、推理行为策略
    thinking_config: dict[str, Any] = field(default_factory=lambda: {"type": "disabled"})
    query_runner: Callable[..., AsyncIterator[Message]] | None = None


@dataclass
class ToolUseContext:
    # Tool配置:是否允许中断、是否保留结果、超时设置、调用模式
    options: ToolUseOptions = field(default_factory=ToolUseOptions)
    # User、System、Tool、Assistant消息
    messages: list[Message] = field(default_factory=list)
    # 当前应用状态：界面状态、任务状态、缓存数据、sessions中的共享变量
    app_state: AppState = field(default_factory=AppState)
    # 本次Tool调用唯一ID
    tool_use_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    agent_id: str | None = None
    # 填充后的系统提示词
    rendered_system_prompt: str | None = None
    # 中断控制器：取消正在执行的工具、停止异步、控制超时、手动终止
    abort_controller: AbortController = field(default_factory=AbortController)
    # 是否保留Tool结果
    preserve_tool_use_results: bool = False
    # 内容替换状态，模版替换变量、占位符替换
    content_replacement_state: dict[str, Any] = field(default_factory=dict)

    def getAppState(self) -> AppState:
        return self.app_state

    def setAppState(self, updater: Callable[[AppState], AppState]) -> None:
        self.app_state = updater(self.app_state)

    def setAppStateForTasks(self, updater: Callable[[AppState], AppState]) -> None:
        self.app_state = updater(self.app_state)

    def pushApiMetricsEntry(self, _ttft_ms: int) -> None:
        return None

    def setToolJSX(self, _payload: Any) -> None:
        return None


def create_user_message(content: Any, is_meta: bool = False) -> Message:
    return Message(type="user", content=_coerce_blocks(content), is_meta=is_meta)


def create_assistant_message(
    content: Any, usage: dict[str, Any] | None = None, request_id: str | None = None
) -> Message:
    return Message(
        type="assistant",
        content=_coerce_blocks(content),
        usage=usage or default_usage(),
        request_id=request_id,
    )


def create_progress_payload(message: Message, prompt: str | None, agent_id: str) -> dict[str, Any]:
    return {"type": "agent_progress", "message": message, "prompt": prompt, "agentId": agent_id}


def extract_text_content(content: Iterable[dict[str, Any]] | None, joiner: str = "\n") -> str:
    if not content:
        return ""
    texts = [str(block.get("text", "")) for block in content if block.get("type") == "text"]
    return joiner.join(part for part in texts if part)


def normalizeMessages(messages: Iterable[Message]) -> list[Message]:
    return [deepcopy(message) for message in messages]


def buildSubagentLookups(messages: Iterable[dict[str, Any]]) -> dict[str, Any]:
    in_progress: set[str] = set()
    for message in messages:
        if message.get("type") == "assistant":
            for block in message.get("content", []):
                if block.get("type") == "tool_use":
                    in_progress.add(str(block.get("id", "")))
        elif message.get("type") == "user":
            for block in message.get("content", []):
                if block.get("type") == "tool_result":
                    in_progress.discard(str(block.get("tool_use_id", "")))
    return {"lookups": {}, "inProgressToolUseIDs": in_progress}


EMPTY_LOOKUPS: dict[str, Any] = {"lookups": {}, "inProgressToolUseIDs": set()}


def count_tokens_from_usage(usage: dict[str, Any] | None) -> int:
    if not usage:
        return 0
    values = [
        usage.get("input_tokens", 0),
        usage.get("output_tokens", 0),
        usage.get("cache_creation_input_tokens", 0) or 0,
        usage.get("cache_read_input_tokens", 0) or 0,
    ]
    return sum(int(value or 0) for value in values)


async def default_query_runner(
    *,
    messages: list[Message],
    system_prompt: str,
    user_context: dict[str, str],
    system_context: dict[str, str],
    tool_use_context: ToolUseContext,
    query_source: str,
    max_turns: int | None,
) -> AsyncIterator[Message]:
    del system_prompt, user_context, system_context, tool_use_context, max_turns
    prompt = extract_text_content(messages[-1].content if messages else [])
    response = (
        f"Scope: {query_source or 'agent task'}\n"
        f"Result: {prompt.strip() or 'No prompt was provided.'}\n"
        f"Key files: none\n"
        f"Issues: none"
    )
    usage = default_usage()
    usage["input_tokens"] = max(len(prompt.split()), 1)
    usage["output_tokens"] = max(len(response.split()), 1)
    yield create_assistant_message(response, usage=usage)


@contextlib.contextmanager
def pushd(path: str | os.PathLike[str] | None):
    if path is None:
        yield
        return
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def ensure_directory(path: str | os.PathLike[str]) -> Path:
    resolved = Path(path)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def create_agent_id() -> str:
    return uuid.uuid4().hex


async def maybe_await(value: Awaitable[Any] | Any) -> Any:
    if asyncio.iscoroutine(value) or isinstance(value, Awaitable):
        return await value
    return value

