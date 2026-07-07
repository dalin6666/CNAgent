from __future__ import annotations

"""Auto-generated Python mirror of `D:/code_project/claude-code-main/tools/TaskUpdateTool/prompt.ts`."""

from typing import Any
from .._mirror import placeholder_class, placeholder_function

SOURCE_PATH = r"D:/code_project/claude-code-main/tools/TaskUpdateTool/prompt.ts"
__all__ = ['DESCRIPTION', 'PROMPT']

DESCRIPTION = 'Update a task in the task list'
PROMPT = "Use this tool to update a task in the task list.\n\n## When to Use This Tool\n\n**Mark tasks as resolved:**\n- When you have completed the work described in a task\n- When a task is no longer needed or has been superseded\n- IMPORTANT: Always mark your assigned tasks as resolved when you finish them\n- After resolving, call TaskList to find your next task\n\n- ONLY mark a task as completed when you have FULLY accomplished it\n- If you encounter errors, blockers, or cannot finish, keep the task as in_progress\n- When blocked, create a new task describing what needs to be resolved\n- Never mark a task as completed if:\n  - Tests are failing\n  - Implementation is partial\n  - You encountered unresolved errors\n  - You couldn't find necessary files or dependencies\n\n**Delete tasks:**\n- When a task is no longer relevant or was created in error\n- Setting status to \\"
