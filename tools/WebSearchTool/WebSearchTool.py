from __future__ import annotations

from typing import Any

from .._runtime import SimpleTool, duckduckgo_search, now_ms


def _call(query: str, allowed_domains: list[str] | None = None, blocked_domains: list[str] | None = None, **_kwargs: Any) -> dict[str, Any]:
    start = now_ms()
    results = duckduckgo_search(query, allowed_domains=allowed_domains, blocked_domains=blocked_domains)
    return {'data': {'query': query, 'results': results, 'durationSeconds': round((now_ms() - start) / 1000, 3)}}


WebSearchTool = SimpleTool(
    name='WebSearch',
    description_text='Search the public web for current information using DuckDuckGo HTML results.',
    prompt_text='Use when you need fresh web results and a simple list of hit titles and URLs is enough.',
    call_handler=_call,
    input_schema={'query': 'search query', 'allowed_domains': 'optional domain allowlist', 'blocked_domains': 'optional domain denylist'},
    output_schema={'results': 'search result hits'},
    user_facing_name='Web Search',
)
