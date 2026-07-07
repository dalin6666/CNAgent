from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

from .._runtime import SimpleTool, ToolUseContext, expand_path

# 从附件中读取前1500字符文本
def _attachment_snippet(item: Any, cwd: str | None) -> str:
    if isinstance(item, str):
        path = expand_path(item, cwd) if item else item
        if path and Path(path).exists():
            return Path(path).read_text(encoding='utf-8', errors='replace')[:1500]
        return item
    if isinstance(item, dict):
        if 'content' in item:
            return str(item['content'])[:1500]
        if 'path' in item:
            path = expand_path(str(item['path']), cwd)
            if Path(path).exists():
                return Path(path).read_text(encoding='utf-8', errors='replace')[:1500]
        return str(item)
    return str(item)


def _call(prompt: str, attachments: list[Any] | None = None, title: str | None = None, max_chars: int = 4000, toolUseContext: ToolUseContext | None = None, **_kwargs: Any) -> dict[str, Any]:
    cwd = toolUseContext.options.cwd if toolUseContext else None
    pieces = [title or 'Brief', prompt]
    for attachment in attachments or []:
        snippet = _attachment_snippet(attachment, cwd)
        if snippet:
            pieces.append(snippet)
    summary = textwrap.shorten(' '.join(piece.replace('\n', ' ') for piece in pieces), width=max_chars, placeholder=' ...')
    return {'data': {'title': title or 'Brief', 'summary': summary, 'attachmentCount': len(attachments or [])}}


BriefTool = SimpleTool(
    name='Brief',
    description_text='Create a compact brief from a prompt plus optional attachments.',
    prompt_text='Use when you want a concise briefing package gathered into one result.',
    call_handler=_call,
    input_schema={'prompt': 'briefing request', 'attachments': 'optional attachment paths or content'},
    output_schema={'summary': 'generated brief text'},
    user_facing_name='Brief',
)
