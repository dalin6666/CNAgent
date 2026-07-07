from __future__ import annotations

from ..config import RuntimeConfig
from ..providers.base import BaseModelProvider


class FallbackManager:
    def __init__(self, providers: list[BaseModelProvider]) -> None:
        self.providers: dict[str, BaseModelProvider] = {}
        for provider in providers:
            self.providers[provider.model_name] = provider
            self.providers[getattr(provider, "provider_id", provider.model_name)] = provider

    def chain(self, config: RuntimeConfig) -> list[BaseModelProvider]:
        ordered_names = [
            config.model_policy.primary_model,
            *config.model_policy.fallback_models,
        ]
        seen: set[str] = set()
        chain: list[BaseModelProvider] = []
        for name in ordered_names:
            if name in seen:
                continue
            provider = self.providers.get(name)
            if provider is None:
                continue
            seen.add(name)
            seen.add(getattr(provider, "provider_id", provider.model_name))
            seen.add(provider.model_name)
            chain.append(provider)
        if chain:
            return chain
        # If primary/fallback names do not resolve, keep the configured provider order.
        ordered: list[BaseModelProvider] = []
        dedup: set[str] = set()
        for provider in self.providers.values():
            provider_key = getattr(provider, "provider_id", provider.model_name)
            if provider_key in dedup:
                continue
            dedup.add(provider_key)
            ordered.append(provider)
        return ordered
