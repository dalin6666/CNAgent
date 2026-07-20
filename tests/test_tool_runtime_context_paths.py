from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agent_runtime.config import RuntimeConfig
from agent_runtime.errors import PathOutsideWorkspaceError
from agent_runtime.runtime.engine import AgentRuntime
from agent_runtime.schemas import SessionState
from agent_runtime.tools.base import ToolRuntimeContext
from agent_runtime.tools.builtin_glob_search import GlobSearchTool
from agent_runtime.tools.builtin_read_file import ReadFileTool
from agent_runtime.tools import PermissionManager, create_tool_registry


def make_context(root: Path, current: Path | None = None) -> ToolRuntimeContext:
    current = current or root
    return ToolRuntimeContext(
        session=SessionState(),
        working_directory=str(current),
        workspace_root=str(root),
        config=object(),
        telemetry=object(),
        interrupt_controller=None,
    )


def test_resolve_path_allows_paths_inside_workspace(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    source = root / "src"
    source.mkdir(parents=True)
    context = make_context(root, source)

    assert context.resolve_path("main.py") == source / "main.py"
    assert context.resolve_path(str(root / "README.md")) == root / "README.md"
    assert context.resolve_path(".") == source


@pytest.mark.parametrize("path", ["../../outside.txt", "../..\\outside.txt"])
def test_resolve_path_rejects_parent_traversal(tmp_path: Path, path: str) -> None:
    root = tmp_path / "workspace"
    current = root / "src"
    current.mkdir(parents=True)
    context = make_context(root, current)

    with pytest.raises(PathOutsideWorkspaceError):
        context.resolve_path(path)


def test_resolve_path_rejects_absolute_path_outside_workspace(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    root.mkdir()
    outside.write_text("outside", encoding="utf-8")
    context = make_context(root)

    with pytest.raises(PathOutsideWorkspaceError):
        context.resolve_path(outside)


def test_resolve_path_rejects_symlink_to_outside_workspace(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / "external"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symbolic links are unavailable: {exc}")

    context = make_context(root)
    with pytest.raises(PathOutsideWorkspaceError):
        context.resolve_path("external/secret.txt")


def test_set_working_directory_keeps_session_inside_workspace(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    child = root / "child"
    child.mkdir(parents=True)
    context = make_context(root, child)

    assert context.set_working_directory("..") == str(root)
    assert context.session.metadata["working_directory"] == str(root)

    with pytest.raises(PathOutsideWorkspaceError):
        context.set_working_directory("..")

    assert context.working_directory == str(root)
    assert context.session.metadata["working_directory"] == str(root)


def test_runtime_rejects_session_working_directory_outside_workspace(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    runtime = AgentRuntime(config=RuntimeConfig(working_directory=str(root)))
    session = SessionState(metadata={"working_directory": str(outside)})

    with pytest.raises(PathOutsideWorkspaceError):
        runtime._session_working_directory(session)


def test_runtime_converts_invalid_session_directory_to_tool_error(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    runtime = AgentRuntime(
        config=RuntimeConfig(
            working_directory=str(root),
            log_dir=str(tmp_path / "logs"),
        ),
        tool_registry=create_tool_registry(),
        permission_manager=PermissionManager(allowed_groups={"lookup"}),
    )
    session = SessionState(metadata={"working_directory": str(outside)})

    from agent_runtime.runtime.telemetry import TelemetryRecorder

    telemetry = TelemetryRecorder(str(tmp_path / "telemetry"), session.session_id)

    async def collect_events():
        events = []
        async for event in runtime._stream_tool_execution(
            tool_name="echo",
            arguments={"text": "hello"},
            tool_call_id="call-1",
            session=session,
            telemetry=telemetry,
            result_sink=[],
        ):
            events.append(event)
        return events

    events = asyncio.run(collect_events())

    assert events[-1].data["is_error"] is True
    assert session.messages[-1].metadata["is_error"] is True


def test_builtin_file_tools_reject_external_paths(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    root.mkdir()
    outside.write_text("outside", encoding="utf-8")
    context = make_context(root)

    with pytest.raises(PathOutsideWorkspaceError):
        asyncio.run(ReadFileTool().run({"path": str(outside)}, context))

    with pytest.raises(PathOutsideWorkspaceError):
        asyncio.run(GlobSearchTool().run({"base_path": str(outside), "pattern": "*"}, context))
