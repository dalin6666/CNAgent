from __future__ import annotations

import os
from typing import Any

from .._runtime import ToolUseContext
from .._session_state import (
    create_worktree_for_session,
    find_canonical_git_root,
    get_current_worktree_session,
    get_plan_slug,
    get_session_id,
    save_worktree_state,
    set_original_cwd,
)
from .constants import ENTER_WORKTREE_TOOL_NAME
from .prompt import getEnterWorktreeToolPrompt


class PythonEnterWorktreeTool:
    name = ENTER_WORKTREE_TOOL_NAME
    search_hint = "create an isolated git worktree and switch into it"
    max_result_size_chars = 100_000
    should_defer = True
    input_schema = {
        "name": (
            'Optional name for the worktree. Each "/"-separated segment may contain '
            "only letters, digits, dots, underscores, and dashes; max 64 chars total."
        )
    }
    output_schema = {
        "worktreePath": "filesystem path of the worktree",
        "worktreeBranch": "worktree branch name",
        "message": "human-readable confirmation",
    }

    async def description(self, _input_data: dict[str, Any] | None = None) -> str:
        return "Creates an isolated git worktree and switches the session into it"

    async def prompt(self) -> str:
        return getEnterWorktreeToolPrompt()

    def userFacingName(self, _input_data: dict[str, Any] | None = None) -> str:
        return "Creating worktree"

    def toAutoClassifierInput(self, input_data: dict[str, Any]) -> str:
        return str(input_data.get("name") or "")

    async def call(
        self,
        *args: Any,
        name: str | None = None,
        toolUseContext: ToolUseContext | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        if args and isinstance(args[0], dict):
            payload = dict(args[0])
            name = payload.get("name", name)

        context = toolUseContext or ToolUseContext()
        state = context.getAppState()

        if get_current_worktree_session(state):
            raise ValueError("Already in a worktree session")

        current_cwd = str(context.options.cwd or os.getcwd())
        main_repo_root = find_canonical_git_root(current_cwd)
        if main_repo_root and main_repo_root != current_cwd:
            os.chdir(main_repo_root)
            context.options.cwd = main_repo_root
            current_cwd = main_repo_root

        slug = str(name).strip() if isinstance(name, str) and name.strip() else get_plan_slug(state)
        worktree_session = create_worktree_for_session(
            state,
            get_session_id(state),
            slug,
            current_cwd,
        )

        worktree_path = str(worktree_session["worktreePath"])
        os.chdir(worktree_path)
        context.options.cwd = worktree_path
        set_original_cwd(state, worktree_path)
        save_worktree_state(state, worktree_session)

        branch = worktree_session.get("worktreeBranch")
        branch_info = f" on branch {branch}" if branch else ""
        return {
            "data": {
                "worktreeId": worktree_session.get("id"),
                "worktreePath": worktree_path,
                "worktreeBranch": branch,
                "message": (
                    f"Created worktree at {worktree_path}{branch_info}. "
                    "The session is now working in the worktree. "
                    "Use ExitWorktree to leave mid-session."
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


EnterWorktreeTool = PythonEnterWorktreeTool()

__all__ = ["EnterWorktreeTool", "PythonEnterWorktreeTool"]
