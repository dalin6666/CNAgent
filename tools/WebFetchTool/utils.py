from __future__ import annotations

from typing import Any

from .._runtime import fetch_url_text

MAX_MARKDOWN_LENGTH = 20000


def isPreapprovedUrl(url: str) -> bool:
    return url.startswith('https://docs.python.org/') or url.startswith('https://developer.mozilla.org/')


def getURLMarkdownContent(url: str, abort_controller: Any = None) -> dict[str, Any]:
    del abort_controller
    response = fetch_url_text(url)
    response['content'] = response['text'][:MAX_MARKDOWN_LENGTH]
    return response


def applyPromptToMarkdown(prompt: str, content: str) -> str:
    if 'summary' in prompt.casefold() or 'summarize' in prompt.casefold():
        return content[:2000]
    return f'Prompt: {prompt}\n\nContent:\n{content[:4000]}'
