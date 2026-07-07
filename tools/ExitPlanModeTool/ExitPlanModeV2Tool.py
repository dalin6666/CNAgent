from __future__ import annotations

import json
import uuid
from typing import Any

from .._runtime import ToolUseContext
from .._session_state import get_plan_file_path, read_plan, write_plan
from ..AgentTool.constants import AGENT_TOOL_NAME
from ..TeamCreateTool.constants import TEAM_CREATE_TOOL_NAME
from .constants import EXIT_PLAN_MODE_V2_TOOL_NAME
from .prompt import EXIT_PLAN_MODE_V2_TOOL_PROMPT


def _tool_matches_name(tool: Any, name: str) -> bool:
    if getattr(tool, "name", None) == name:
        return True
    aliases = getattr(tool, "aliases", ()) or ()
    return name in aliases


def _is_teammate(context: ToolUseContext, state: Any) -> bool:
    if bool((getattr(state, "metadata", None) or {}).get("is_teammate")):
        return True
    if context.agent_id:
        task = (getattr(state, "tasks", None) or {}).get(context.agent_id, {})
        return isinstance(task, dict) and "team" in task
    return False


def _is_plan_mode_required(state: Any) -> bool:
    return bool((getattr(state, "metadata", None) or {}).get("plan_mode_required"))


def _get_agent_name(context: ToolUseContext, state: Any) -> str:
    metadata = getattr(state, "metadata", None) or {}
    agent_name = metadata.get("agent_name")
    if isinstance(agent_name, str) and agent_name:
        return agent_name
    if context.agent_id:
        return str(context.agent_id)
    return "unknown"


def _get_team_name(context: ToolUseContext, state: Any) -> str | None:
    metadata = getattr(state, "metadata", None) or {}
    team_name = metadata.get("team_name")
    if isinstance(team_name, str) and team_name:
        return team_name
    if context.agent_id:
        task = (getattr(state, "tasks", None) or {}).get(context.agent_id, {})
        if isinstance(task, dict) and task.get("team"):
            return str(task["team"])
    return None


def _generate_request_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class PythonExitPlanModeV2Tool:
    name = EXIT_PLAN_MODE_V2_TOOL_NAME
    search_hint = "present plan for approval and start coding (plan mode only)"
    max_result_size_chars = 100_000
    should_defer = True
    input_schema = {
        "allowedPrompts": "Optional prompt-based permissions needed to implement the approved plan.",
        "plan": "Optional edited plan content injected by the caller before exit approval.",
        "planFilePath": "Optional injected plan file path.",
    }
    output_schema = {
        "plan": "the plan that was presented to the user",
        "isAgent": "whether the caller was an agent context",
        "filePath": "the file path where the plan was saved",
        "hasTaskTool": "whether the Agent tool is available",
        "planWasEdited": "whether the incoming plan differed from the on-disk copy",
        "awaitingLeaderApproval": "whether a teammate is waiting for team lead approval",
        "requestId": "approval request id when relevant",
    }

    async def description(self, _input_data: dict[str, Any] | None = None) -> str:
        return "Prompts the user to exit plan mode and start coding"

    async def prompt(self) -> str:
        return EXIT_PLAN_MODE_V2_TOOL_PROMPT

    def userFacingName(self, _input_data: dict[str, Any] | None = None) -> str:
        return ""

    def isEnabled(self, context: ToolUseContext | None = None) -> bool:
        if context is None:
            return True
        state = context.getAppState()
        return len(getattr(state, "allowed_channels", [])) == 0

    def isConcurrencySafe(self, _input_data: dict[str, Any] | None = None) -> bool:
        return True

    def isReadOnly(self, _input_data: dict[str, Any] | None = None) -> bool:
        return False

    def requiresUserInteraction(self, context: ToolUseContext | None = None) -> bool:
        if context is None:
            return True
        return not _is_teammate(context, context.getAppState())

    async def validateInput(
        self,
        _input_data: dict[str, Any],
        context: ToolUseContext | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        if context is None:
            return {"result": True}
        state = context.getAppState()
        if _is_teammate(context, state):
            return {"result": True}
        mode = str((getattr(state, "tool_permission_context", None) or {}).get("mode", "default"))
        if mode != "plan":
            return {
                "result": False,
                "message": (
                    "You are not in plan mode. This tool is only for exiting plan mode "
                    "after writing a plan. If your plan was already approved, continue "
                    "with implementation."
                ),
                "errorCode": 1,
            }
        return {"result": True}

    async def checkPermissions(
        self,
        input_data: dict[str, Any],
        context: ToolUseContext | None = None,
    ) -> dict[str, Any]:
        if context is not None and _is_teammate(context, context.getAppState()):
            return {"behavior": "allow", "updatedInput": input_data}
        return {
            "behavior": "ask",
            "message": "Exit plan mode?",
            "updatedInput": input_data,
        }

    async def call(
        self,
        *args: Any,
        toolUseContext: ToolUseContext | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload = dict(kwargs)
        if args and isinstance(args[0], dict):
            payload.update(dict(args[0]))

        context = toolUseContext or ToolUseContext()
        state = context.getAppState()
        is_agent = bool(context.agent_id)

        file_path = str(payload.get("planFilePath") or get_plan_file_path(state, context.agent_id))
        input_plan = payload.get("plan")
        if not isinstance(input_plan, str):
            input_plan = None
        plan = input_plan if input_plan is not None else read_plan(state, context.agent_id)

        if input_plan is not None:
            file_path = write_plan(state, input_plan, context.agent_id)
            plan = input_plan

        if _is_teammate(context, state) and _is_plan_mode_required(state):
            if not plan:
                raise ValueError(
                    f"No plan file found at {file_path}. Please write your plan to this file before calling ExitPlanMode."
                )

            agent_name = _get_agent_name(context, state)
            team_name = _get_team_name(context, state)
            request_id = _generate_request_id("plan_approval")
            approval_request = {
                "type": "plan_approval_request",
                "from": agent_name,
                "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z",
                "planFilePath": file_path,
                "planContent": plan,
                "requestId": request_id,
            }
            state.mailboxes.setdefault("team-lead", []).append(
                {
                    "from": agent_name,
                    "team": team_name,
                    "text": json.dumps(approval_request, ensure_ascii=False),
                }
            )
            if context.agent_id and context.agent_id in state.tasks:
                task = state.tasks[context.agent_id]
                if isinstance(task, dict):
                    task["awaiting_plan_approval"] = True
            return {
                "data": {
                    "plan": plan,
                    "isAgent": True,
                    "filePath": file_path,
                    "awaitingLeaderApproval": True,
                    "requestId": request_id,
                }
            }

        permission_context = dict(getattr(state, "tool_permission_context", None) or {})
        restore_mode = str(permission_context.get("prePlanMode") or "default")
        if restore_mode == "auto" and not bool((getattr(state, "metadata", None) or {}).get("auto_mode_gate_enabled", True)):
            restore_mode = "default"

        state.plan_mode = False
        state.has_exited_plan_mode = True
        state.needs_plan_mode_exit_attachment = True
        if permission_context.get("prePlanMode") == "auto" and restore_mode != "auto":
            state.needs_auto_mode_exit_attachment = True
        permission_context["mode"] = restore_mode
        permission_context["prePlanMode"] = None
        state.tool_permission_context = permission_context
        state.config["toolPermissionContext"] = dict(permission_context)

        has_task_tool = any(
            _tool_matches_name(tool, AGENT_TOOL_NAME)
            for tool in (context.options.tools or [])
        )

        return {
            "data": {
                "plan": plan,
                "isAgent": is_agent,
                "filePath": file_path,
                "hasTaskTool": has_task_tool or None,
                "planWasEdited": (input_plan is not None) or None,
            }
        }

    def mapToolResultToToolResultBlockParam(
        self,
        output: dict[str, Any],
        tool_use_id: str,
    ) -> dict[str, Any]:
        if output.get("awaitingLeaderApproval"):
            return {
                "type": "tool_result",
                "content": (
                    "Your plan has been submitted to the team lead for approval.\n\n"
                    f"Plan file: {output.get('filePath')}\n\n"
                    "**What happens next:**\n"
                    "1. Wait for the team lead to review your plan\n"
                    "2. You will receive a message in your inbox with approval or rejection\n"
                    "3. If approved, you can proceed with implementation\n"
                    "4. If rejected, refine your plan based on the feedback\n\n"
                    "**Important:** Do NOT proceed until you receive approval. Check your inbox for response.\n\n"
                    f"Request ID: {output.get('requestId')}"
                ),
                "tool_use_id": tool_use_id,
            }

        if output.get("isAgent"):
            return {
                "type": "tool_result",
                "content": (
                    'User has approved the plan. There is nothing else needed from you now. '
                    'Please respond with "ok"'
                ),
                "tool_use_id": tool_use_id,
            }

        plan = str(output.get("plan") or "")
        if not plan.strip():
            return {
                "type": "tool_result",
                "content": "User has approved exiting plan mode. You can now proceed.",
                "tool_use_id": tool_use_id,
            }

        team_hint = ""
        if output.get("hasTaskTool"):
            team_hint = (
                f"\n\nIf this plan can be broken down into multiple independent tasks, "
                f"consider using the {TEAM_CREATE_TOOL_NAME} tool to create a team and "
                "parallelize the work."
            )

        plan_label = (
            "Approved Plan (edited by user)"
            if output.get("planWasEdited")
            else "Approved Plan"
        )
        return {
            "type": "tool_result",
            "content": (
                "User has approved your plan. You can now start coding. "
                "Start with updating your todo list if applicable.\n\n"
                f"Your plan has been saved to: {output.get('filePath')}\n"
                f"You can refer back to it if needed during implementation.{team_hint}\n\n"
                f"## {plan_label}:\n{plan}"
            ),
            "tool_use_id": tool_use_id,
        }


ExitPlanModeV2Tool = PythonExitPlanModeV2Tool()

__all__ = ["ExitPlanModeV2Tool", "PythonExitPlanModeV2Tool"]
