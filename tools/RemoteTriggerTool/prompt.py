from __future__ import annotations

"""Auto-generated Python mirror of `D:/code_project/claude-code-main/tools/RemoteTriggerTool/prompt.ts`."""

from typing import Any
from .._mirror import placeholder_class, placeholder_function

SOURCE_PATH = r"D:/code_project/claude-code-main/tools/RemoteTriggerTool/prompt.ts"
__all__ = ['DESCRIPTION', 'PROMPT', 'REMOTE_TRIGGER_TOOL_NAME']

DESCRIPTION = 'Manage scheduled remote Claude Code agents (triggers) via the claude.ai CCR API. Auth is handled in-process — the token never reaches the shell.'
PROMPT = 'Call the claude.ai remote-trigger API. Use this instead of curl — the OAuth token is added automatically in-process and never exposed.\n\nActions:\n- list: GET /v1/code/triggers\n- get: GET /v1/code/triggers/{trigger_id}\n- create: POST /v1/code/triggers (requires body)\n- update: POST /v1/code/triggers/{trigger_id} (requires body, partial update)\n- run: POST /v1/code/triggers/{trigger_id}/run\n\nThe response is the raw JSON from the API.'
REMOTE_TRIGGER_TOOL_NAME = 'RemoteTrigger'
