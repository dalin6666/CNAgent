from __future__ import annotations

from dataclasses import dataclass, field

from ..schemas import Message


@dataclass(slots=True)
class MemoryEntry:
    text: str
    keywords: set[str] = field(default_factory=set)


class MemoryPrefetcher:
    def __init__(self) -> None:
        self._entries: list[MemoryEntry] = []

    def register(self, text: str, keywords: set[str] | None = None) -> None:
        self._entries.append(MemoryEntry(text=text, keywords=keywords or set()))

    def prefetch(self, query: str, limit: int = 3) -> list[MemoryEntry]:
        query_terms = set(query.lower().split())
        ranked = sorted(
            self._entries,
            key=lambda entry: len(entry.keywords & query_terms),
            reverse=True,
        )
        return [entry for entry in ranked if entry.keywords & query_terms][:limit]

    def build_messages(self, query: str) -> list[Message]:
        memories = self.prefetch(query)
        if not memories:
            return []
        lines = [f"- {entry.text}" for entry in memories]
        return [
            Message(
                role="system",
                content="Prefetched memory notes:\n" + "\n".join(lines),
                metadata={"source": "memory_prefetch"},
            )
        ]
