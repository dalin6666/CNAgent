from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..errors import ToolPermissionError
from ..schemas import ToolResult
from .base import BaseTool, ToolRuntimeContext
from .registry import ToolRegistry

_LEGACY_ADAPTER_CACHE: tuple[list["LegacyToolAdapter"], list[str]] | None = None


def _to_json_schema(raw_schema: Any) -> dict[str, Any]:
    if isinstance(raw_schema, dict) and raw_schema.get("type") == "object":
        return raw_schema
    if isinstance(raw_schema, dict):
        properties: dict[str, Any] = {}
        for key, value in raw_schema.items():
            if isinstance(value, dict):
                properties[str(key)] = value
            else:
                properties[str(key)] = {
                    "type": "string",
                    "description": str(value),
                }
        return {"type": "object", "properties": properties}
    return {"type": "object", "properties": {}}


def _callable_description(tool: Any, fallback: str) -> str:
    description_text = getattr(tool, "description_text", None)
    if isinstance(description_text, str) and description_text.strip():
        return description_text.strip()
    search_hint = getattr(tool, "search_hint", None)
    if isinstance(search_hint, str) and search_hint.strip():
        return search_hint.strip()
    description = getattr(tool, "description", None)
    if isinstance(description, str) and description.strip():
        return description.strip()
    return fallback


def _module_metadata(legacy_tool: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        module = importlib.import_module(legacy_tool.__class__.__module__)
    except Exception:  # noqa: BLE001
        return {}, {}
    input_schema = getattr(module, "INPUT_SCHEMA", {}) or {}
    output_schema = getattr(module, "OUTPUT_SCHEMA", {}) or {}
    return (
        input_schema if isinstance(input_schema, dict) else {},
        output_schema if isinstance(output_schema, dict) else {},
    )


def _guess_permission_group(export_name: str, tool_name: str, legacy_tool: Any) -> str:
    lowered = {export_name.lower(), tool_name.lower()}
    if export_name.lower().endswith("tool"):
        lowered.add(export_name.lower()[:-4])
    read_names = {
        "read",
        "glob",
        "grep",
        "toolsearch",
        "taskget",
        "tasklist",
        "taskoutput",
        "lsp",
    }
    lookup_names = {"websearch", "webfetch", "skill", "brief"}
    mcp_names = {"mcp", "listmcpresources", "readmcpresource", "mcpauth"}
    exec_names = {"bash", "powershell", "sleep"}
    agent_names = {"agent"}
    interactive_names = {"askuserquestion"}
    automation_names = {"croncreate", "crondelete", "cronlist", "remotetrigger"}
    state_names = {
        "config",
        "enterplanmode",
        "exitplanmodev2",
        "enterworktree",
        "exitworktree",
        "taskcreate",
        "taskupdate",
        "taskstop",
        "teamcreate",
        "teamdelete",
        "todowrite",
        "sendmessage",
        "syntheticoutput",
    }
    write_names = {"edit", "write", "notebookedit"}

    if lowered & read_names:
        return "read"
    if lowered & lookup_names:
        return "lookup"
    if lowered & mcp_names:
        return "mcp"
    if lowered & exec_names:
        return "exec"
    if lowered & write_names:
        return "write"
    if lowered & state_names:
        return "state"
    if lowered & automation_names:
        return "automation"
    if lowered & agent_names:
        return "agent"
    if lowered & interactive_names:
        return "interactive"

    is_read_only = getattr(legacy_tool, "isReadOnly", None)
    if callable(is_read_only):
        try:
            if bool(is_read_only({})):
                return "read"
        except TypeError:
            try:
                if bool(is_read_only()):
                    return "read"
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            pass
    return "legacy"


def _unwrap_legacy_output(result: Any) -> Any:
    if isinstance(result, dict) and set(result.keys()) == {"data"}:
        return result["data"]
    return result


def _render_summary(
    legacy_tool: Any,
    output: Any,
    tool_call_id: str,
    fallback: str,
    *,
    max_chars: int = 600,
) -> str:
    mapper = getattr(legacy_tool, "mapToolResultToToolResultBlockParam", None)
    if callable(mapper):
        try:
            mapped = mapper(output, tool_call_id)
            content = mapped.get("content") if isinstance(mapped, dict) else None
            if isinstance(content, list):
                rendered = "\n".join(str(item) for item in content)
            elif content is not None:
                rendered = str(content)
            else:
                rendered = _default_output_summary(output, fallback)
            return rendered[:max_chars]
        except Exception:  # noqa: BLE001
            pass
    return _default_output_summary(output, fallback)[:max_chars]


def _default_output_summary(output: Any, fallback: str) -> str:
    if isinstance(output, str) and output.strip():
        return output
    if not isinstance(output, dict):
        return fallback

    for key in ("stdout", "message", "content", "text", "error"):
        value = output.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    filenames = output.get("filenames")
    if isinstance(filenames, list) and filenames:
        return "\n".join(str(item) for item in filenames[:12])

    results = output.get("results")
    if isinstance(results, list) and results:
        rendered_results: list[str] = []
        for item in results[:8]:
            if isinstance(item, dict):
                title = item.get("title") or item.get("name") or item.get("url")
                rendered_results.append(str(title or item))
            else:
                rendered_results.append(str(item))
        return "\n".join(rendered_results)

    task = output.get("task")
    if isinstance(task, dict):
        task_id = task.get("id")
        subject = task.get("subject")
        if task_id or subject:
            return f"{task_id or 'task'} {subject or ''}".strip()

    return fallback


@dataclass(slots=True)
class LegacyContextBundle:
    kind: str
    context: Any
    working_directory: str
    pushd: Callable[[str | None], Any]


@dataclass(slots=True)
class _InterruptControllerProxy:
    controller: Any

    @property
    def aborted(self) -> bool:
        return bool(
            getattr(self.controller, "aborted", False)
            or getattr(self.controller, "interrupted", False)
        )

    @property
    def interrupted(self) -> bool:
        return self.aborted

    @property
    def signal(self) -> "_InterruptControllerProxy":
        return self

    def abort(self) -> None:
        if hasattr(self.controller, "abort"):
            self.controller.abort()
            return
        if hasattr(self.controller, "interrupt"):
            self.controller.interrupt("legacy_tool_abort")
            return
        setattr(self.controller, "interrupted", True)


class LegacyToolAdapter(BaseTool):
    def __init__(self, export_name: str, legacy_tool: Any) -> None:
        self.export_name = export_name
        self.legacy_tool = legacy_tool
        self.name = str(getattr(legacy_tool, "name", export_name))
        self.description = _callable_description(
            legacy_tool,
            f"Legacy adapter for top-level tool export {export_name}.",
        )
        module_input_schema, self.legacy_output_schema = _module_metadata(legacy_tool)
        raw_input_schema = getattr(legacy_tool, "input_schema", None) or module_input_schema
        self.input_schema = _to_json_schema(raw_input_schema)
        self.output_schema = _to_json_schema(
            getattr(legacy_tool, "output_schema", None) or self.legacy_output_schema
        )
        self.permission_group = _guess_permission_group(
            export_name,
            self.name,
            legacy_tool,
        )
        self.aliases = tuple(
            str(alias)
            for alias in (getattr(legacy_tool, "aliases", None) or ())
            if str(alias).strip()
        )
        self.strict = bool(getattr(legacy_tool, "strict", False))
        self.should_defer = bool(getattr(legacy_tool, "should_defer", False))
        self.max_result_size_chars = getattr(
            legacy_tool,
            "max_result_size_chars",
            None,
        )
        self.requires_user_interaction = bool(self._call_flag("requiresUserInteraction"))
        enabled = self._call_flag("isEnabled")
        self.is_enabled = True if enabled is None else bool(enabled)

    def schema(self) -> dict[str, Any]:
        base = super().schema()
        base["legacy_export_name"] = self.export_name
        base["legacy_module"] = self.legacy_tool.__class__.__module__
        base["legacy_kind"] = type(self.legacy_tool).__name__
        return base

    def summarize(self, arguments: dict[str, Any]) -> str:
        summary_fn = getattr(self.legacy_tool, "getToolUseSummary", None)
        if callable(summary_fn):
            try:
                summary = summary_fn(arguments)
                if summary:
                    return str(summary)
            except Exception:  # noqa: BLE001
                pass
        return super().summarize(arguments)

    async def run(
        self,
        arguments: dict[str, Any],
        context: ToolRuntimeContext,
    ) -> ToolResult:
        payload = {
            key: value
            for key, value in dict(arguments).items()
            if not key.startswith("_")
        }
        tool_call_id = str(arguments.get("_tool_call_id", ""))
        bundle = self._build_legacy_context(context, payload)
        with bundle.pushd(bundle.working_directory):
            self._backfill_observable_input(payload)
            await self._validate(payload, bundle.context)
            await self._check_permissions(payload, bundle.context)
            raw_result = await self._invoke_legacy_tool(payload, bundle.context)
        output = _unwrap_legacy_output(raw_result)
        self._sync_context_back(context, bundle)
        summary = _render_summary(
            self.legacy_tool,
            output,
            tool_call_id,
            self.summarize(payload),
        )
        return self.build_result(
            arguments,
            output=output,
            summary=summary,
        )

    def _build_legacy_context(
        self,
        runtime_context: ToolRuntimeContext,
        payload: dict[str, Any],
    ) -> LegacyContextBundle:
        session = runtime_context.session
        working_directory = str(
            Path(
                session.metadata.get("working_directory", runtime_context.working_directory)
            ).resolve()
        )
        session.metadata["working_directory"] = working_directory

        if self.export_name == "AgentTool":
            from tools.AgentTool.runtimeModels import AppState as AgentAppState
            from tools.AgentTool.runtimeModels import pushd as agent_pushd
            from tools.AgentTool.runtimeModels import ToolUseContext as AgentToolUseContext
            from tools.AgentTool.runtimeModels import ToolUseOptions as AgentToolUseOptions

            legacy_context = session.metadata.get("_legacy_agent_context")
            if legacy_context is None:
                legacy_context = AgentToolUseContext(
                    options=AgentToolUseOptions(query_source="agent_runtime_legacy_adapter"),
                    app_state=AgentAppState(),
                )
                session.metadata["_legacy_agent_context"] = legacy_context
            proxy = _InterruptControllerProxy(runtime_context.interrupt_controller)
            legacy_context.abort_controller = proxy
            if "cwd" not in payload:
                payload["cwd"] = working_directory
            return LegacyContextBundle(
                kind="agent",
                context=legacy_context,
                working_directory=working_directory,
                pushd=agent_pushd,
            )

        from tools._runtime import ToolUseContext as LegacyToolUseContext
        from tools._runtime import ToolUseOptions as LegacyToolUseOptions
        from tools._runtime import default_tool_permission_context, get_global_app_state
        from tools._runtime import pushd as legacy_pushd

        legacy_context = session.metadata.get("_legacy_std_context")
        if legacy_context is None:
            app_state = get_global_app_state()
            app_state.tool_permission_context = default_tool_permission_context()
            legacy_context = LegacyToolUseContext(
                options=LegacyToolUseOptions(
                    cwd=working_directory,
                    query_source="agent_runtime_legacy_adapter",
                ),
                app_state=app_state,
                read_file_state=session.metadata.setdefault(
                    "_legacy_read_file_state",
                    {},
                ),
            )
            session.metadata["_legacy_std_context"] = legacy_context

        permission_context = dict(getattr(legacy_context.app_state, "tool_permission_context", {}) or {})
        permission_context.update(
            {
                "mode": permission_context.get("mode", "default"),
                "allowed_directories": [working_directory],
                "working_directories": [working_directory],
                "additionalWorkingDirectories": permission_context.get(
                    "additionalWorkingDirectories",
                    {},
                ),
            }
        )
        legacy_context.app_state.tool_permission_context = permission_context
        legacy_context.options.cwd = working_directory
        proxy = _InterruptControllerProxy(runtime_context.interrupt_controller)
        legacy_context.abort_controller = proxy
        setattr(legacy_context, "abortController", proxy)
        return LegacyContextBundle(
            kind="standard",
            context=legacy_context,
            working_directory=working_directory,
            pushd=legacy_pushd,
        )

    def _backfill_observable_input(self, payload: dict[str, Any]) -> None:
        method = getattr(self.legacy_tool, "backfillObservableInput", None)
        if callable(method):
            method(payload)

    async def _validate(self, payload: dict[str, Any], legacy_context: Any) -> None:
        validator = getattr(self.legacy_tool, "validateInput", None)
        if not callable(validator):
            return
        result = await self._call_compat(
            validator,
            payload,
            context=legacy_context,
        )
        if isinstance(result, dict) and not result.get("result", True):
            raise ValueError(str(result.get("message", "Legacy tool validation failed.")))

    async def _check_permissions(self, payload: dict[str, Any], legacy_context: Any) -> None:
        checker = getattr(self.legacy_tool, "checkPermissions", None)
        if not callable(checker):
            return
        result = await self._call_compat(
            checker,
            payload,
            context=legacy_context,
        )
        if not isinstance(result, dict):
            return
        behavior = str(result.get("behavior", "allow"))
        if behavior == "deny":
            raise ToolPermissionError(str(result.get("message", "Legacy permission denied.")))
        if behavior == "ask":
            if self.permission_group in {
                "exec",
                "state",
                "interactive",
                "agent",
                "automation",
                "lookup",
                "mcp",
                "legacy",
            }:
                return
            raise ToolPermissionError(
                str(
                    result.get(
                        "message",
                        "Legacy tool requires an interactive permission prompt.",
                    )
                )
            )

    async def _invoke_legacy_tool(self, payload: dict[str, Any], legacy_context: Any) -> Any:
        caller = getattr(self.legacy_tool, "call", None)
        if not callable(caller):
            raise TypeError(f"Legacy tool {self.export_name} does not expose call().")
        attempts = [
            lambda: caller(payload, toolUseContext=legacy_context),
            lambda: caller(toolUseContext=legacy_context, **payload),
            lambda: caller(payload),
            lambda: caller(**payload),
        ]
        last_error: Exception | None = None
        for attempt in attempts:
            try:
                result = attempt()
                if inspect.isawaitable(result):
                    result = await result
                return result
            except TypeError as exc:
                last_error = exc
                continue
        assert last_error is not None
        raise last_error

    async def _call_compat(
        self,
        callable_obj: Any,
        payload: dict[str, Any],
        *,
        context: Any,
    ) -> Any:
        attempts = [
            lambda: callable_obj(payload, context),
            lambda: callable_obj(payload, toolUseContext=context),
            lambda: callable_obj(payload, _context=context),
            lambda: callable_obj(payload),
        ]
        last_error: Exception | None = None
        for attempt in attempts:
            try:
                result = attempt()
                if inspect.isawaitable(result):
                    result = await result
                return result
            except TypeError as exc:
                last_error = exc
                continue
        assert last_error is not None
        raise last_error

    def _sync_context_back(
        self,
        runtime_context: ToolRuntimeContext,
        bundle: LegacyContextBundle,
    ) -> None:
        if bundle.kind == "agent":
            runtime_context.session.metadata["legacy_agent_active"] = True
            return
        cwd = getattr(bundle.context.options, "cwd", None)
        if cwd:
            runtime_context.session.metadata["working_directory"] = str(Path(cwd).resolve())
        permission_context = getattr(bundle.context.app_state, "tool_permission_context", None)
        if permission_context is not None:
            if isinstance(permission_context, dict):
                runtime_context.session.metadata["legacy_tool_permission_context"] = dict(
                    permission_context
                )
            elif hasattr(permission_context, "__dict__"):
                runtime_context.session.metadata["legacy_tool_permission_context"] = dict(
                    vars(permission_context)
                )

    def _call_flag(self, name: str) -> Any:
        method = getattr(self.legacy_tool, name, None)
        if callable(method):
            try:
                return method()
            except TypeError:
                return None
            except Exception:  # noqa: BLE001
                return None
        return None


def load_legacy_tool_adapters(
    *,
    refresh: bool = False,
) -> tuple[list[LegacyToolAdapter], list[str]]:
    global _LEGACY_ADAPTER_CACHE
    if _LEGACY_ADAPTER_CACHE is not None and not refresh:
        return _LEGACY_ADAPTER_CACHE
    try:
        legacy_root = importlib.import_module("tools")
    except Exception as exc:  # noqa: BLE001
        return [], [f"Failed to import top-level tools package: {exc}"]

    adapters: list[LegacyToolAdapter] = []
    failures: list[str] = []
    exports = list(getattr(legacy_root, "__all__", []))
    for export_name in exports:
        try:
            legacy_tool = getattr(legacy_root, export_name)
            if not hasattr(legacy_tool, "call"):
                continue
            adapters.append(LegacyToolAdapter(export_name, legacy_tool))
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{export_name}: {exc}")
    _LEGACY_ADAPTER_CACHE = (adapters, failures)
    return _LEGACY_ADAPTER_CACHE


def register_legacy_tool_adapters(registry: ToolRegistry) -> dict[str, Any]:
    adapters, failures = load_legacy_tool_adapters()
    registered = registry.register_many(adapters)
    return {
        "registered": [adapter.name for adapter in registered],
        "failed": failures,
    }
