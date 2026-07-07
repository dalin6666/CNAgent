from __future__ import annotations

import os
from functools import lru_cache
from typing import TypedDict

DEFAULT_MAX_OUTPUT_TOKENS = 25_000
DEFAULT_MAX_OUTPUT_SIZE_BYTES = 256 * 1024


class FileReadingLimits(TypedDict, total=False):
    maxTokens: int
    maxSizeBytes: int
    includeMaxSizeInPrompt: bool
    targetedRangeNudge: bool


def _get_env_max_tokens() -> int | None:
    override = os.environ.get('CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS')
    if not override:
        return None
    try:
        parsed = int(override)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


@lru_cache(maxsize=1)
def getDefaultFileReadingLimits() -> FileReadingLimits:
    env_max_tokens = _get_env_max_tokens()
    return {
        'maxTokens': env_max_tokens or DEFAULT_MAX_OUTPUT_TOKENS,
        'maxSizeBytes': DEFAULT_MAX_OUTPUT_SIZE_BYTES,
    }


__all__ = [
    'DEFAULT_MAX_OUTPUT_TOKENS',
    'DEFAULT_MAX_OUTPUT_SIZE_BYTES',
    'FileReadingLimits',
    'getDefaultFileReadingLimits',
]
