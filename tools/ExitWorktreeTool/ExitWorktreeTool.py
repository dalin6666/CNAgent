from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .._runtime import ToolUseContext
from .._session_state import (
    get_current_worktree_session,
    get_original_cwd,
    get_project_root,
    save_worktree_state,
    set_original_cwd,
    set_project_root,
)
from .constants import EXIT_WORKTREE_TOOL_NAME
from .prompt import getExitWorktreeToolPrompt


def _run_git_no_throw(args: list[str], cwd: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )


def _count_worktree_changes(
    worktree_path: str,
    original_head_commit: str | None,
) -> dict[str, int] | None:
    status = _run_git_no_throw(["status", "--porcelain"], worktree_path)
    if status.returncode != 0:
        return None

    changed_files = sum(1 for line in status.stdout.splitlines() if line.strip())
    if not original_head_commit:
        return None

    rev_list = _run_git_no_throw(
        ["rev-list", "--count", f"{original_head_commit}..HEAD"],
        worktree_path,
    )
    if rev_list.returncode != 0:
        return None

    try:
        commits = int(rev_list.stdout.strip() or "0")
    except ValueError:
        commits = 0
    return {"changedFiles": changed_files, "commits": commits}


def _normalize_input(input_data: dict[str, Any]) -> dict[str, Any]:
    payload = dict(input_data)
    action = payload.get("action")
    if action is None and "remove" in payload:
        action = "remove" if bool(payload.get("remove")) else "keep"
    if action is not None:
        payload["action"] = action
    if "discard_changes" not in payload:
        payload["discard_changes"] = False
    return payload


def _restore_session_to_original_cwd(
    *,
    state: Any,
    context: ToolUseContext,
    original_cwd: str,
    project_root_is_worktree: bool,
) -> None:
    resolved_original = str(Path(original_cwd).resolve())
    os.chdir(resolved_original)
    context.options.cwd = resolved_original
    set_original_cwd(state, resolved_original)
    if project_root_is_worktree:
        set_project_root(state, resolved_original)
    save_worktree_state(state, None)
    context.read_file_state.clear()


def _mark_worktree_record_inactive(state: Any, session: dict[str, Any], *, remove: bool) -> None:
    session_id = session.get("id")
    if not isinstance(session_id, str) or not session_id:
        return
    record = state.worktrees.get(session_id)
    if isinstance(record, dict):
        record["active"] = False
        if remove:
            state.worktrees.pop(session_id, None)


def _kill_tmux_session(session_name: str) -> bool:
    try:
        result = subprocess.run(
            ["tmux", "kill-session", "-t", session_name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _cleanup_git_worktree(original_cwd: str, worktree_path: str) -> str | None:
    remove_result = _run_git_no_throw(
        ["worktree", "remove", "--force", worktree_path],
        original_cwd,
    )
    if remove_result.returncode != 0:
        return remove_result.stderr.strip() or remove_result.stdout.strip() or "Failed to remove worktree"
    return None


def _delete_git_worktree_branch(original_cwd: str, worktree_branch: str | None) -> str | None:
    if not worktree_branch:
        return None
    delete_result = _run_git_no_throw(["branch", "-D", worktree_branch], original_cwd)
    if delete_result.returncode != 0:
        return (
            delete_result.stderr.strip()
            or delete_result.stdout.strip()
            or f"Failed to delete branch {worktree_branch}"
        )
    return None


class PythonExitWorktreeTool:
    name = EXIT_WORKTREE_TOOL_NAME
    search_hint = "exit a worktree session and return to the original directory"
    max_result_size_chars = 100_000
    should_defer = True
    input_schema = {
        "action": (
            '"keep" leaves the worktree and branch on disk; '
            '"remove" deletes both.'
        ),
        "discard_changes": (
            'Required true when action is "remove" and the worktree has '
            "uncommitted files or unmerged commits."
        ),
    }
    output_schema = {
        "action": "the performed action",
        "originalCwd": "the directory restored after exiting the worktree",
        "worktreePath": "the worktree path that was exited",
        "worktreeBranch": "the worktree branch, when available",
        "tmuxSessionName": "the tmux session left running when action=keep",
        "discardedFiles": "number of discarded uncommitted files for action=remove",
        "discardedCommits": "number of discarded commits for action=remove",
        "message": "human-readable confirmation",
    }

    async def description(self, _input_data: dict[str, Any] | None = None) -> str:
        return (
            "Exits a worktree session created by EnterWorktree and restores "
            "the original working directory"
        )

    async def prompt(self) -> str:
        return getExitWorktreeToolPrompt()

    def userFacingName(self, _input_data: dict[str, Any] | None = None) -> str:
        return "Exiting worktree"

    def isDestructive(self, input_data: dict[str, Any]) -> bool:
        payload = _normalize_input(input_data)
        return payload.get("action") == "remove"

    def toAutoClassifierInput(self, input_data: dict[str, Any]) -> str:
        payload = _normalize_input(input_data)
        return str(payload.get("action") or "")

    async def validateInput(
        self,
        input_data: dict[str, Any],
        context: ToolUseContext | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        payload = _normalize_input(input_data)
        action = payload.get("action")
        if action not in {"keep", "remove"}:
            return {
                "result": False,
                "message": 'Invalid action. Expected "keep" or "remove".',
                "errorCode": 4,
            }

        tool_context = context or ToolUseContext()
        state = tool_context.getAppState()
        session = get_current_worktree_session(state)
        if not session:
            return {
                "result": False,
                "message": (
                    "No-op: there is no active EnterWorktree session to exit. "
                    "This tool only operates on worktrees created by EnterWorktree "
                    "in the current session. No filesystem changes were made."
                ),
                "errorCode": 1,
            }

        if action == "remove" and not bool(payload.get("discard_changes")):
            summary = _count_worktree_changes(
                str(session.get("worktreePath") or ""),
                session.get("originalHeadCommit"),
            )
            if summary is None:
                return {
                    "result": False,
                    "message": (
                        f'Could not verify worktree state at {session.get("worktreePath")}. '
                        "Refusing to remove without explicit confirmation. "
                        'Re-invoke with discard_changes: true to proceed, or use '
                        'action: "keep" to preserve the worktree.'
                    ),
                    "errorCode": 3,
                }

            changed_files = int(summary["changedFiles"])
            commits = int(summary["commits"])
            if changed_files > 0 or commits > 0:
                parts: list[str] = []
                branch_name = str(session.get("worktreeBranch") or "the worktree branch")
                if changed_files > 0:
                    file_label = "file" if changed_files == 1 else "files"
                    parts.append(f"{changed_files} uncommitted {file_label}")
                if commits > 0:
                    commit_label = "commit" if commits == 1 else "commits"
                    parts.append(f"{commits} {commit_label} on {branch_name}")
                return {
                    "result": False,
                    "message": (
                        f'Worktree has {" and ".join(parts)}. Removing will discard '
                        "this work permanently. Confirm with the user, then "
                        "re-invoke with discard_changes: true, or use "
                        'action: "keep" to preserve the worktree.'
                    ),
                    "errorCode": 2,
                }

        return {"result": True}

    async def call(
        self,
        *args: Any,
        toolUseContext: ToolUseContext | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload = dict(kwargs)
        if args and isinstance(args[0], dict):
            payload.update(dict(args[0]))
        payload = _normalize_input(payload)

        action = payload.get("action")
        if action not in {"keep", "remove"}:
            raise ValueError('Invalid action. Expected "keep" or "remove".')

        context = toolUseContext or ToolUseContext()
        state = context.getAppState()
        session = get_current_worktree_session(state)
        if not session:
            raise ValueError("Not in a worktree session")

        original_cwd = str(session["originalCwd"])
        worktree_path = str(session["worktreePath"])
        worktree_branch = session.get("worktreeBranch")
        tmux_session_name = session.get("tmuxSessionName")
        original_head_commit = session.get("originalHeadCommit")
        hook_based = bool(session.get("hookBased"))

        project_root_is_worktree = get_project_root(state) == get_original_cwd(state)
        summary = _count_worktree_changes(worktree_path, original_head_commit) or {
            "changedFiles": 0,
            "commits": 0,
        }
        changed_files = int(summary["changedFiles"])
        commits = int(summary["commits"])

        if action == "keep":
            _restore_session_to_original_cwd(
                state=state,
                context=context,
                original_cwd=original_cwd,
                project_root_is_worktree=project_root_is_worktree,
            )
            _mark_worktree_record_inactive(state, session, remove=False)

            tmux_note = ""
            if isinstance(tmux_session_name, str) and tmux_session_name:
                tmux_note = (
                    f" Tmux session {tmux_session_name} is still running; "
                    f"reattach with: tmux attach -t {tmux_session_name}"
                )

            branch_note = f" on branch {worktree_branch}" if worktree_branch else ""
            return {
                "data": {
                    "action": "keep",
                    "originalCwd": original_cwd,
                    "worktreePath": worktree_path,
                    "worktreeBranch": worktree_branch,
                    "tmuxSessionName": tmux_session_name,
                    "message": (
                        f"Exited worktree. Your work is preserved at {worktree_path}"
                        f"{branch_note}. Session is now back in {original_cwd}.{tmux_note}"
                    ),
                }
            }

        if isinstance(tmux_session_name, str) and tmux_session_name:
            _kill_tmux_session(tmux_session_name)

        resolved_original = str(Path(original_cwd).resolve())
        os.chdir(resolved_original)
        cleanup_warnings: list[str] = []

        if hook_based:
            if Path(worktree_path).exists():
                shutil.rmtree(worktree_path, ignore_errors=True)
        else:
            remove_warning = _cleanup_git_worktree(resolved_original, worktree_path)
            if remove_warning:
                cleanup_warnings.append(f"Worktree removal reported: {remove_warning}")
            branch_warning = _delete_git_worktree_branch(resolved_original, worktree_branch)
            if branch_warning:
                cleanup_warnings.append(f"Branch cleanup reported: {branch_warning}")

        _restore_session_to_original_cwd(
            state=state,
            context=context,
            original_cwd=original_cwd,
            project_root_is_worktree=project_root_is_worktree,
        )
        _mark_worktree_record_inactive(state, session, remove=True)

        discard_parts: list[str] = []
        if commits > 0:
            commit_label = "commit" if commits == 1 else "commits"
            discard_parts.append(f"{commits} {commit_label}")
        if changed_files > 0:
            file_label = "file" if changed_files == 1 else "files"
            discard_parts.append(f"{changed_files} uncommitted {file_label}")
        discard_note = (
            f' Discarded {" and ".join(discard_parts)}.' if discard_parts else ""
        )
        warning_note = (
            f' Cleanup warning: {" ".join(cleanup_warnings)}'
            if cleanup_warnings
            else ""
        )

        return {
            "data": {
                "action": "remove",
                "originalCwd": original_cwd,
                "worktreePath": worktree_path,
                "worktreeBranch": worktree_branch,
                "discardedFiles": changed_files or None,
                "discardedCommits": commits or None,
                "message": (
                    f"Exited and removed worktree at {worktree_path}.{discard_note} "
                    f"Session is now back in {original_cwd}.{warning_note}"
                ),
            }
        }

    def mapToolResultToToolResultBlockParam(
        self,
        output: dict[str, Any],
        tool_use_id: str,
    ) -> dict[str, Any]:
        return {
            "type": "tool_result",
            "content": str(output.get("message", "")),
            "tool_use_id": tool_use_id,
        }


ExitWorktreeTool = PythonExitWorktreeTool()

__all__ = ["ExitWorktreeTool", "PythonExitWorktreeTool"]
