from __future__ import annotations

import os

from ..AskUserQuestionTool.prompt import ASK_USER_QUESTION_TOOL_NAME


WHAT_HAPPENS_SECTION = f"""## What Happens in Plan Mode

In plan mode, you'll:
1. Thoroughly explore the codebase using Glob, Grep, and Read tools
2. Understand existing patterns and architecture
3. Design an implementation approach
4. Present your plan to the user for approval
5. Use {ASK_USER_QUESTION_TOOL_NAME} if you need to clarify approaches
6. Exit plan mode with ExitPlanMode when ready to implement

"""


def _env_truthy(name: str) -> bool:
    value = os.getenv(name, '')
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def isPlanModeInterviewPhaseEnabled() -> bool:
    if os.getenv('USER_TYPE') == 'ant':
        return True
    return _env_truthy('CLAUDE_CODE_PLAN_MODE_INTERVIEW_PHASE')


def getEnterPlanModeToolPromptExternal() -> str:
    what_happens = '' if isPlanModeInterviewPhaseEnabled() else WHAT_HAPPENS_SECTION
    return f"""Use this tool proactively when you're about to start a non-trivial implementation task. Getting user sign-off on your approach before writing code prevents wasted effort and ensures alignment. This tool transitions you into plan mode where you can explore the codebase and design an implementation approach for user approval.

## When to Use This Tool

Prefer using EnterPlanMode for implementation tasks unless they are simple. Use it when any of these conditions apply:

1. New feature work: adding meaningful new functionality.
2. Multiple valid approaches: the task can be solved in several different ways.
3. Code modifications: the change affects existing behavior or structure.
4. Architectural decisions: you need to choose between patterns or technologies.
5. Multi-file changes: the task will likely touch more than 2-3 files.
6. Unclear requirements: you need exploration before you understand the full scope.
7. User preferences matter: you would otherwise need {ASK_USER_QUESTION_TOOL_NAME} just to pick an approach.

## When NOT to Use This Tool

Skip EnterPlanMode for simple tasks:
- Single-line or few-line fixes
- Adding a single function with clear requirements
- Tasks where the user already gave very specific instructions
- Pure research or exploration tasks

{what_happens}## Examples

### GOOD - Use EnterPlanMode:
User: "Add user authentication to the app"
User: "Optimize the database queries"
User: "Implement dark mode"
User: "Update the error handling in the API"

### BAD - Don't use EnterPlanMode:
User: "Fix the typo in the README"
User: "Add a console.log to debug this function"
User: "What files handle routing?"

## Important Notes

- This tool requires user approval before implementation should begin
- If you are unsure, err on the side of planning first
"""


def getEnterPlanModeToolPromptAnt() -> str:
    what_happens = '' if isPlanModeInterviewPhaseEnabled() else WHAT_HAPPENS_SECTION
    return f"""Use this tool when a task has genuine ambiguity about the right approach and getting user input before coding would prevent significant rework. This tool transitions you into plan mode where you can explore the codebase and design an implementation approach for user approval.

## When to Use This Tool

Plan mode is valuable when the implementation approach is genuinely unclear. Use it when:

1. Significant architectural ambiguity exists.
2. Requirements are unclear and need exploration.
3. The task would significantly restructure existing code.

## When NOT to Use This Tool

Skip plan mode when you can reasonably infer the right approach:
- Straightforward implementation work even if it touches multiple files
- Requests with specific enough instructions
- Clear bug fixes
- Research or exploration tasks

When in doubt, prefer starting work and using {ASK_USER_QUESTION_TOOL_NAME} for focused questions.

{what_happens}## Important Notes

- This tool requires user approval before coding
"""


def getEnterPlanModeToolPrompt() -> str:
    return (
        getEnterPlanModeToolPromptAnt()
        if os.getenv('USER_TYPE') == 'ant'
        else getEnterPlanModeToolPromptExternal()
    )


__all__ = ['getEnterPlanModeToolPrompt', 'isPlanModeInterviewPhaseEnabled']
