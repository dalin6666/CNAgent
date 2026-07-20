from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from ..config import RuntimeConfig
from ..errors import (
    PathOutsideWorkspaceError,
    ProviderExecutionError,
    PromptTooLongError,
    ToolExecutionError,
    UserInterruptedError,
)
from ..events import RuntimeEvent
from ..providers.base import BaseModelProvider
from ..providers.mock_provider import MockModelProvider
from ..providers.openai_compatible import OpenAICompatibleProvider
from ..schemas import Attachment, Message, ModelRequest, SessionState, ToolResult
from ..tools import (
    PermissionManager,
    ToolRegistry,
    create_tool_registry,
    register_legacy_tool_adapters,
)
from ..tools.base import ToolRuntimeContext
from .attachments import AttachmentManager
from .budget import TokenBudgetManager
from .compression import ContextCompressor
from .fallback import FallbackManager
from .hooks import StopHookContext, StopHookManager
from .interruption import InterruptController
from .mcp import MCPToolDiscovery
from .memory import MemoryPrefetcher
from .skills import SkillPrefetcher
from .telemetry import TelemetryRecorder

# 单轮对话的状态容器，存放在每一轮模型执行时临时创建、传递、更新的状态对象
@dataclass(slots=True)
class _TurnState:
    assistant_chunks: list[str] = field(default_factory=list)  # 保存流式输出的文本片段
    tool_results: list[ToolResult] = field(default_factory=list)
    # 调用了哪些工具，调用id、名称、参数
    tool_calls: list[dict[str, object]] = field(default_factory=list)
    stop_reason: str = "end_turn"
    assistant_tool_message_index: int | None = None

    @property
    def assistant_text(self) -> str:
        return "".join(self.assistant_chunks)


class AgentRuntime:
    def __init__(
        self,
        *,
        # 控制最大turn数、context、最大输出token、是否使用MCP、是否启用skill、允许哪些工具权限组、日志记录等
        config: RuntimeConfig | None = None,
        providers: list[BaseModelProvider] | None = None,
        # 保存可用工具，提供describe_tools()给模型看tool schema,提供require(tool_name)给runtime看具体tool对象
        tool_registry: ToolRegistry | None = None,
        # Tool权限管理器，Tool执行前调用ensure_allowed()防止运行未授权权限组的工具
        permission_manager: PermissionManager | None = None,
        budget_manager: TokenBudgetManager | None = None,
        compressor: ContextCompressor | None = None,
        attachment_manager: AttachmentManager | None = None,
        memory_prefetcher: MemoryPrefetcher | None = None,
        skill_prefetcher: SkillPrefetcher | None = None,
        mcp_discovery: MCPToolDiscovery | None = None,
        stop_hooks: StopHookManager | None = None,
        interrupt_controller: InterruptController | None = None,
    ) -> None:
        self.config = config or RuntimeConfig()
        # 设置根目录
        self._workspace_root = Path(self.config.working_directory).expanduser().resolve(
            strict=False
        )
        self.providers = providers or [MockModelProvider(self.config.model_policy.primary_model)]
        self.tool_registry = tool_registry or ToolRegistry()
        self.permission_manager = permission_manager or PermissionManager(
            allowed_groups=set(self.config.allowed_tool_groups)
        )
        self.budget_manager = budget_manager or TokenBudgetManager()
        self.compressor = compressor or ContextCompressor(
            self.budget_manager,
            log_dir=self.config.log_dir,
        )
        self.attachment_manager = attachment_manager or AttachmentManager()
        self.memory_prefetcher = memory_prefetcher or MemoryPrefetcher()
        self.skill_prefetcher = skill_prefetcher or SkillPrefetcher()
        self.mcp_discovery = mcp_discovery or MCPToolDiscovery()
        self.stop_hooks = stop_hooks or StopHookManager()
        self.interrupt_controller = interrupt_controller or InterruptController()
        self.fallback_manager = FallbackManager(self.providers)

    async def stream(
        self,
        user_text: str,
        *,
        session: SessionState | None = None,
        attachments: list[Attachment] | None = None,
        watched_paths: list[str] | None = None,
    ):
        session = session or SessionState()
        attachments = attachments or []
        watched_paths = watched_paths or []
        telemetry = TelemetryRecorder(self.config.log_dir, session.session_id)
        session.metadata.setdefault(
            "working_directory",
            str(self._workspace_root),
        )

        yield RuntimeEvent(
            kind="run_started",
            message="agent run started",
            data={"session_id": session.session_id},
        )
        telemetry.emit("run_started", session_id=session.session_id)

        await self._register_dynamic_tools(user_text, telemetry)
        self._inject_prefetch_messages(
            user_text=user_text,
            session=session,
            attachments=attachments,
            watched_paths=watched_paths,
        )

        session.messages.append(
            Message(
                role="user",
                content=user_text,
                metadata={"source": "user"},
            )
        )

        stop_reason = "end_turn"
        while session.turn_count < self.config.max_turns:
            self.interrupt_controller.raise_if_interrupted()
            session.turn_count += 1
            yield RuntimeEvent(
                kind="turn_started",
                message=f"turn {session.turn_count} started",
                data={"turn": session.turn_count},
            )
            telemetry.emit("turn_started", turn=session.turn_count)

            turn_completed = False
            retry_current_turn = False
            for provider in self.fallback_manager.chain(self.config):
                session.active_model = provider.model_name
                turn_state = _TurnState()
                try:
                    with telemetry.span(
                        "provider_turn",
                        provider=provider.model_name,
                        turn=session.turn_count,
                    ):
                        async for event in self._stream_single_turn(
                            provider=provider,
                            session=session,
                            telemetry=telemetry,
                            turn_state=turn_state,
                        ):
                            yield event
                except PromptTooLongError as exc:
                    recovered, recovery_notes = self.compressor.recover_from_error(
                        session=session,
                        config=self.config,
                        error=exc,
                        provider_context_limit=min(
                            provider.max_context_tokens,
                            self.config.context_window_tokens,
                        ),
                    )
                    if recovered:
                        telemetry.emit(
                            "reactive_compact_recovery",
                            provider=provider.model_name,
                            notes=recovery_notes,
                        )
                        yield RuntimeEvent(
                            kind="recovery",
                            message="reactive compact recovered from prompt overflow",
                            data={
                                "provider": provider.model_name,
                                "notes": recovery_notes,
                            },
                        )
                        retry_current_turn = True
                        break
                    session.compression_level += 1
                    telemetry.emit(
                        "prompt_too_long",
                        provider=provider.model_name,
                        compression_level=session.compression_level,
                        error=str(exc),
                    )
                    yield RuntimeEvent(
                        kind="recovery",
                        message="prompt too long, retrying with stronger compression",
                        data={
                            "provider": provider.model_name,
                            "compression_level": session.compression_level,
                        },
                    )
                    if session.compression_level <= self.config.prompt_too_long_retries:
                        retry_current_turn = True
                        break
                    yield RuntimeEvent(
                        kind="model_fallback",
                        message=f"{provider.model_name} failed after compression retries",
                        data={"provider": provider.model_name, "reason": str(exc)},
                    )
                    continue
                except UserInterruptedError:
                    telemetry.emit("run_interrupted", turn=session.turn_count)
                    raise
                except Exception as exc:  # noqa: BLE001
                    recovered, recovery_notes = self.compressor.recover_from_error(
                        session=session,
                        config=self.config,
                        error=exc,
                        provider_context_limit=min(
                            provider.max_context_tokens,
                            self.config.context_window_tokens,
                        ),
                    )
                    if recovered:
                        telemetry.emit(
                            "reactive_compact_recovery",
                            provider=provider.model_name,
                            notes=recovery_notes,
                        )
                        yield RuntimeEvent(
                            kind="recovery",
                            message="reactive compact recovered from provider error",
                            data={
                                "provider": provider.model_name,
                                "notes": recovery_notes,
                            },
                        )
                        retry_current_turn = True
                        break
                    telemetry.emit(
                        "provider_error",
                        provider=provider.model_name,
                        turn=session.turn_count,
                        error=str(exc),
                    )
                    yield RuntimeEvent(
                        kind="model_fallback",
                        message=f"provider failed: {provider.model_name}",
                        data={"provider": provider.model_name, "error": str(exc)},
                    )
                    continue

                stop_reason = turn_state.stop_reason

                if turn_state.tool_calls:
                    self._finalize_assistant_tool_message(session, turn_state, provider.model_name)
                elif turn_state.assistant_text:
                    session.messages.append(
                        Message(
                            role="assistant",
                            content=turn_state.assistant_text,
                            metadata={
                                "provider": provider.model_name,
                                "turn": session.turn_count,
                            },
                        )
                    )
                self.compressor.on_successful_turn(session)

                if turn_state.tool_results:
                    turn_completed = True
                    break

                if stop_reason == "max_output_tokens":
                    if session.continuation_count >= self.config.max_continuations:
                        turn_completed = True
                        break
                    session.continuation_count += 1
                    session.messages.append(
                        Message(
                            role="user",
                            content=self.config.continue_prompt,
                            metadata={
                                "synthetic": True,
                                "continuation": session.continuation_count,
                            },
                        )
                    )
                    telemetry.emit(
                        "continuation_scheduled",
                        continuation_count=session.continuation_count,
                        provider=provider.model_name,
                    )
                    yield RuntimeEvent(
                        kind="continuation_scheduled",
                        message="max output reached, scheduling continuation",
                        data={"continuation_count": session.continuation_count},
                    )
                    turn_completed = True
                    break

                turn_completed = True
                session.finished = True
                break

            if retry_current_turn:
                session.turn_count -= 1
                continue

            if not turn_completed:
                raise ProviderExecutionError("All configured providers failed for this turn.")

            yield RuntimeEvent(
                kind="turn_finished",
                message=f"turn {session.turn_count} finished",
                data={"turn": session.turn_count, "stop_reason": stop_reason},
            )
            telemetry.emit(
                "turn_finished",
                turn=session.turn_count,
                stop_reason=stop_reason,
            )

            if session.finished and stop_reason != "max_output_tokens":
                break

        if session.turn_count >= self.config.max_turns and not session.finished:
            stop_reason = "max_turns"

        final_text = self._final_assistant_text(session)
        hook_results = await self.stop_hooks.run_all(
            StopHookContext(
                session=session,
                final_text=final_text,
                stop_reason=stop_reason,
                metadata={"active_model": session.active_model},
            )
        )
        telemetry.emit(
            "run_finished",
            turns=session.turn_count,
            stop_reason=stop_reason,
            hooks=len(hook_results),
        )
        yield RuntimeEvent(
            kind="run_finished",
            message="agent run finished",
            data={
                "session_id": session.session_id,
                "turns": session.turn_count,
                "stop_reason": stop_reason,
                "hook_results": hook_results,
            },
        )

    async def _stream_single_turn(
        self,
        *,
        provider: BaseModelProvider,
        session: SessionState,
        telemetry: TelemetryRecorder,
        turn_state: _TurnState,
    ):
        prepared_messages, notes = self.compressor.fit_messages(
            session.messages,
            self.config,
            session=session,
            provider_context_limit=min(
                provider.max_context_tokens,
                self.config.context_window_tokens,
            ),
            compression_level=session.compression_level,
        )

        request = ModelRequest(
            messages=prepared_messages,
            available_tools=self.tool_registry.describe_tools(),
            model=provider.model_name,
            system_prompt=self.config.system_prompt,
            max_output_tokens=min(
                self.config.max_output_tokens,
                provider.max_output_tokens,
            ),
            metadata={
                "working_directory": self._session_working_directory(session),
                "continuation_count": session.continuation_count,
                "turn": session.turn_count,
            },
        )

        if notes:
            yield RuntimeEvent(
                kind="context_compressed",
                message="context was compressed to fit budget",
                data={"provider": provider.model_name, "notes": notes},
            )

        async for chunk in provider.stream(request):
            self.interrupt_controller.raise_if_interrupted()
            if chunk.kind == "text_delta":
                turn_state.assistant_chunks.append(chunk.text)
                yield RuntimeEvent(
                    kind="text_delta",
                    text=chunk.text,
                    data={"provider": provider.model_name, "turn": session.turn_count},
                )
                telemetry.emit(
                    "text_delta",
                    provider=provider.model_name,
                    turn=session.turn_count,
                    size=len(chunk.text),
                )
                if turn_state.assistant_tool_message_index is not None:
                    session.messages[turn_state.assistant_tool_message_index].content = (
                        turn_state.assistant_text
                    )
            elif chunk.kind == "tool_call" and chunk.tool_call is not None:
                telemetry.emit(
                    "tool_call_requested",
                    tool=chunk.tool_call.name,
                    provider=provider.model_name,
                )
                self._record_assistant_tool_call(session, turn_state, chunk.tool_call, provider.model_name)
                yield RuntimeEvent(
                    kind="tool_call",
                    message=f"tool requested: {chunk.tool_call.name}",
                    data={
                        "provider": provider.model_name,
                        "tool": chunk.tool_call.name,
                        "arguments": chunk.tool_call.arguments,
                    },
                )
                async for tool_event in self._stream_tool_execution(
                    tool_name=chunk.tool_call.name,
                    arguments=chunk.tool_call.arguments,
                    tool_call_id=chunk.tool_call.id,
                    session=session,
                    telemetry=telemetry,
                    result_sink=turn_state.tool_results,
                ):
                    yield tool_event
            elif chunk.kind == "usage":
                session.usage.merge(chunk.usage)
            elif chunk.kind == "done":
                turn_state.stop_reason = chunk.stop_reason or "end_turn"

    async def _stream_tool_execution(
        self,
        tool_name: str,
        arguments: dict,
        *,
        tool_call_id: str,
        session: SessionState,
        telemetry: TelemetryRecorder,
        result_sink: list[ToolResult],
    ):
        tool = self.tool_registry.require(tool_name)
        self.permission_manager.ensure_allowed(tool.name, tool.permission_group)
        run_arguments = dict(arguments)
        run_arguments["_tool_call_id"] = tool_call_id

        start = time.perf_counter()
        telemetry.emit("tool_started", tool=tool_name, arguments=run_arguments)
        yield RuntimeEvent(
            kind="tool_started",
            message=f"tool started: {tool_name}",
            data={"tool": tool_name, "arguments": arguments},
        )
        try:
            context = ToolRuntimeContext(
                session=session,
                working_directory=self._session_working_directory(session),
                workspace_root=self._workspace_root,
                config=self.config,
                telemetry=telemetry,
                interrupt_controller=self.interrupt_controller,
            )
            last_result: ToolResult | None = None
            async for item in tool.stream(run_arguments, context):
                self.interrupt_controller.raise_if_interrupted()
                if isinstance(item, ToolResult):
                    last_result = item
                else:
                    telemetry.emit(
                        "tool_stream_delta",
                        tool=tool_name,
                        text=item.text,
                    )
                    yield RuntimeEvent(
                        kind="tool_delta",
                        text=item.text,
                        data={"tool": tool_name, **item.data},
                    )
            if last_result is None:
                raise ToolExecutionError(f"Tool {tool_name} produced no final result.")
            last_result.duration_ms = (time.perf_counter() - start) * 1000
            result_sink.append(last_result)
            session.messages.append(
                Message(
                    role="tool",
                    name=last_result.name,
                    tool_call_id=last_result.tool_call_id,
                    content=last_result.as_message_content(),
                    metadata={
                        "tool_result": True,
                        "is_error": last_result.is_error,
                    },
                )
            )
            self.compressor.on_tool_result(session, last_result)
            telemetry.emit(
                "tool_finished",
                tool=tool_name,
                duration_ms=last_result.duration_ms,
                is_error=last_result.is_error,
            )
            yield RuntimeEvent(
                kind="tool_finished",
                message=f"tool finished: {tool_name}",
                data={
                    "tool": tool_name,
                    "duration_ms": last_result.duration_ms,
                    "is_error": last_result.is_error,
                    "summary": last_result.summary,
                },
            )
        except Exception as exc:  # noqa: BLE001
            telemetry.emit("tool_error", tool=tool_name, error=str(exc))
            result = ToolResult(
                tool_call_id=tool_call_id,
                name=tool_name,
                output={"error": str(exc)},
                is_error=True,
                duration_ms=(time.perf_counter() - start) * 1000,
                summary="tool execution failed",
            )
            result_sink.append(result)
            session.messages.append(
                Message(
                    role="tool",
                    name=result.name,
                    tool_call_id=result.tool_call_id,
                    content=result.as_message_content(),
                    metadata={"tool_result": True, "is_error": True},
                )
            )
            self.compressor.on_tool_result(session, result)
            yield RuntimeEvent(
                kind="tool_finished",
                message=f"tool finished with error: {tool_name}",
                data={
                    "tool": tool_name,
                    "duration_ms": result.duration_ms,
                    "is_error": True,
                    "summary": result.summary,
                    "error": str(exc),
                },
            )

    async def _register_dynamic_tools(
        self,
        query: str,
        telemetry: TelemetryRecorder,
    ) -> None:
        if not self.config.enable_mcp_discovery:
            return
        discovered = await self.mcp_discovery.discover(query)
        if not discovered:
            return
        self.tool_registry.register_many(discovered)
        telemetry.emit(
            "mcp_tools_registered",
            count=len(discovered),
            tools=[tool.name for tool in discovered],
        )

    def _inject_prefetch_messages(
        self,
        *,
        user_text: str,
        session: SessionState,
        attachments: list[Attachment],
        watched_paths: list[str],
    ) -> None:
        injected: list[Message] = []
        if self.config.enable_memory_prefetch:
            injected.extend(self.memory_prefetcher.build_messages(user_text))
        if self.config.enable_skill_prefetch:
            injected.extend(self.skill_prefetcher.build_messages(user_text))
        injected.extend(
            self.attachment_manager.build_messages(
                attachments=attachments,
                watched_paths=watched_paths,
                session=session,
                config=self.config,
            )
        )
        session.messages.extend(injected)

    def _final_assistant_text(self, session: SessionState) -> str:
        for message in reversed(session.messages):
            if message.role == "assistant":
                return message.content
        return ""

    def _session_working_directory(self, session: SessionState) -> str:
        root = self._workspace_root
        current = Path(
            session.metadata.get("working_directory", self.config.working_directory)
        ).expanduser().resolve(strict=False)
        if not current.is_relative_to(root):
            raise PathOutsideWorkspaceError(
                f"Session working directory is outside the workspace: {current}. "
                f"Workspace root: {root}"
            )
        return str(current)

    def _record_assistant_tool_call(
        self,
        session: SessionState,
        turn_state: _TurnState,
        tool_call: object,
        provider_name: str,
    ) -> None:
        if turn_state.assistant_tool_message_index is None:
            session.messages.append(
                Message(
                    role="assistant",
                    content=turn_state.assistant_text,
                    metadata={
                        "provider": provider_name,
                        "turn": session.turn_count,
                        "tool_calls": [],
                    },
                )
            )
            turn_state.assistant_tool_message_index = len(session.messages) - 1
        payload = {
            "id": getattr(tool_call, "id"),
            "name": getattr(tool_call, "name"),
            "arguments": getattr(tool_call, "arguments"),
        }
        turn_state.tool_calls.append(payload)
        session.messages[turn_state.assistant_tool_message_index].metadata.setdefault(
            "tool_calls",
            [],
        ).append(payload)

    def _finalize_assistant_tool_message(
        self,
        session: SessionState,
        turn_state: _TurnState,
        provider_name: str,
    ) -> None:
        if turn_state.assistant_tool_message_index is None:
            session.messages.append(
                Message(
                    role="assistant",
                    content=turn_state.assistant_text,
                    metadata={
                        "provider": provider_name,
                        "turn": session.turn_count,
                        "tool_calls": list(turn_state.tool_calls),
                    },
                )
            )
            turn_state.assistant_tool_message_index = len(session.messages) - 1
            return
        session.messages[turn_state.assistant_tool_message_index].content = turn_state.assistant_text
        session.messages[turn_state.assistant_tool_message_index].metadata["provider"] = provider_name
        session.messages[turn_state.assistant_tool_message_index].metadata["turn"] = session.turn_count


def create_default_runtime(config: RuntimeConfig | None = None) -> AgentRuntime:
    config = config or RuntimeConfig()
    registry = create_tool_registry(include_legacy=False)
    legacy_manifest: dict[str, object] | None = None
    if config.enable_legacy_tool_adapters:
        legacy_manifest = register_legacy_tool_adapters(registry)

    providers = _build_provider_chain(config)

    runtime = AgentRuntime(
        config=config,
        providers=providers,
        tool_registry=registry,
        permission_manager=PermissionManager(
            allowed_groups=set(config.allowed_tool_groups)
        ),
    )
    runtime.memory_prefetcher.register(
        "Keep answers concise and tool-oriented for codebase tasks.",
        keywords={"codebase", "tool", "agent", "runtime"},
    )
    runtime.skill_prefetcher.register(
        name="code-navigation",
        description="Search files first, then read targeted files.",
        path="agent_runtime/tools",
        keywords={"file", "files", "search", "read", "directory"},
    )
    runtime.stop_hooks.register(
        lambda ctx: {
            "hook": "summary",
            "final_text_chars": len(ctx.final_text),
            "stop_reason": ctx.stop_reason,
        }
    )
    if legacy_manifest is not None:
        runtime.stop_hooks.register(
            lambda _ctx: {
                "hook": "legacy_tools",
                "registered_count": len(legacy_manifest.get("registered", [])),
                "failed_count": len(legacy_manifest.get("failed", [])),
            }
        )
    return runtime


def _build_provider_chain(config: RuntimeConfig) -> list[BaseModelProvider]:
    if config.model_policy.provider_configs:
        ordered_ids = _resolve_provider_order(config)
        providers: list[BaseModelProvider] = []
        seen: set[str] = set()
        for provider_id in ordered_ids:
            settings = config.model_policy.provider_configs.get(provider_id)
            if settings is None or provider_id in seen:
                continue
            seen.add(provider_id)
            if settings.provider_type == "openai_compatible":
                providers.append(OpenAICompatibleProvider(settings))
        if providers:
            return providers

    provider_names = [
        config.model_policy.primary_model,
        *config.model_policy.fallback_models,
    ]
    providers: list[BaseModelProvider] = []
    for index, name in enumerate(dict.fromkeys(provider_names)):
        max_context = 8_000 if index == 0 else 12_000
        providers.append(
            MockModelProvider(
                provider_id=name,
                model_name=name,
                max_context_tokens=max_context,
                max_output_tokens=config.max_output_tokens,
            )
        )
    return providers


def _resolve_provider_order(config: RuntimeConfig) -> list[str]:
    configured_ids = list(config.model_policy.provider_configs.keys())
    primary = config.model_policy.primary_model
    fallbacks = list(config.model_policy.fallback_models)
    mock_defaults = {"mock-sonnet", "mock-haiku"}
    if configured_ids and primary in mock_defaults:
        primary = configured_ids[0]
        fallbacks = [item for item in configured_ids[1:] if item not in mock_defaults]
    order = [primary, *fallbacks]
    for provider_id in configured_ids:
        if provider_id not in order:
            order.append(provider_id)
    return list(dict.fromkeys(order))
