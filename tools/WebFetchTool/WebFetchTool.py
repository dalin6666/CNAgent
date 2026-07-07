from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .._runtime import SimpleTool, now_ms
from .preapproved import isPreapprovedHost
from .utils import applyPromptToMarkdown, getURLMarkdownContent


def _call(url: str, prompt: str, **_kwargs: Any) -> dict[str, Any]:
    start = now_ms()
    parsed = urlparse(url)
    response = getURLMarkdownContent(url)
    result = applyPromptToMarkdown(prompt, response['content'])
    return {'data': {'bytes': response['bytes'], 'code': response['code'], 'codeText': response['codeText'], 'result': result, 'durationMs': now_ms() - start, 'url': response['url'], 'preapproved': isPreapprovedHost(parsed.hostname or '', parsed.path)}}


WebFetchTool = SimpleTool(
    name='WebFetch',
    description_text='Fetch a URL and apply a simple prompt-oriented post-processing step.',
    prompt_text='Use only for public, unauthenticated URLs.',
    call_handler=_call,
    input_schema={'url': 'target URL', 'prompt': 'how to process the fetched content'},
    output_schema={'result': 'processed web content'},
    user_facing_name='Web Fetch',
)
