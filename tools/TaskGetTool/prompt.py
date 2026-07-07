from __future__ import annotations

"""Auto-generated Python mirror of `D:/code_project/claude-code-main/tools/TaskGetTool/prompt.ts`."""

from typing import Any
from .._mirror import placeholder_class, placeholder_function

SOURCE_PATH = r"D:/code_project/claude-code-main/tools/TaskGetTool/prompt.ts"
__all__ = ['DESCRIPTION', 'PROMPT']

DESCRIPTION = 'Get a task by ID from the task list'
PROMPT = "Use this tool to retrieve a task by its ID from the task list.\n\n## When to Use This Tool\n\n- When you need the full description and context before starting work on a task\n- To understand task dependencies (what it blocks, what blocks it)\n- After being assigned a task, to get complete requirements\n\n## Output\n\nReturns full task details:\n- **subject**: Task title\n- **description**: Detailed requirements and context\n- **status**: 'pending', 'in_progress', or 'completed'\n- **blocks**: Tasks waiting on this one to complete\n- **blockedBy**: Tasks that must complete before this one can start\n\n## Tips\n\n- After fetching a task, verify its blockedBy list is empty before beginning work.\n- Use TaskList to see all tasks in summary form.\n"
