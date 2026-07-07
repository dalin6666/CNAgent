from __future__ import annotations

__all__ = ["EXIT_PLAN_MODE_V2_TOOL_PROMPT"]

ASK_USER_QUESTION_TOOL_NAME = "AskUserQuestion"

EXIT_PLAN_MODE_V2_TOOL_PROMPT = f"""Use this tool when you are in plan mode and have finished writing your plan to the plan file and are ready for user approval.

## How This Tool Works
- You should have already written your plan to the plan file specified in the plan mode system message
- This tool does NOT take the plan content as a required parameter; it reads the plan file automatically and also accepts an injected edited plan when the caller provides one
- This tool signals that you are done planning and ready for the user to review and approve
- The user will see the contents of your plan when they review it

## When to Use This Tool
IMPORTANT: Only use this tool when the task requires planning implementation steps for work that will proceed into coding. For research-only tasks where you're gathering information or just reading the codebase, do NOT use this tool.

## Before Using This Tool
Ensure your plan is complete and unambiguous:
- If you have unresolved questions about requirements or approach, use {ASK_USER_QUESTION_TOOL_NAME} first
- Once your plan is finalized, use THIS tool to request approval

Important: Do NOT use {ASK_USER_QUESTION_TOOL_NAME} to ask "Is this plan okay?" or "Should I proceed?" because this tool already performs that approval handoff.
"""
