from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from ..schemas import ModelChunk, ModelRequest


class BaseModelProvider(ABC):
    provider_name = "base"
    provider_id = "base"
    model_name = "base"
    max_context_tokens = 16_000
    max_output_tokens = 1_024
    supports_streaming = True
    supports_tool_calls = True

    @abstractmethod
    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelChunk]:
        raise NotImplementedError
