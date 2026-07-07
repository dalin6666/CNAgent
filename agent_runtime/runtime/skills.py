from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..schemas import Message


@dataclass(slots=True)
class SkillDescriptor:
    name: str
    description: str
    path: str
    keywords: set[str] = field(default_factory=set)


class SkillPrefetcher:
    def __init__(self) -> None:
        self._skills: list[SkillDescriptor] = []

    def register(
        self,
        *,
        name: str,
        description: str,
        path: str,
        keywords: set[str] | None = None,
    ) -> None:
        self._skills.append(
            SkillDescriptor(
                name=name,
                description=description,
                path=path,
                keywords=keywords or set(),
            )
        )

    def discover_from_directory(self, root: str) -> None:
        base = Path(root)
        if not base.exists():
            return
        for skill_file in base.rglob("SKILL.md"):
            description = skill_file.parent.name
            keywords = set(description.lower().split("_"))
            self.register(
                name=skill_file.parent.name,
                description=description,
                path=str(skill_file),
                keywords=keywords,
            )

    def prefetch(self, query: str, limit: int = 3) -> list[SkillDescriptor]:
        query_terms = set(query.lower().split())
        ranked = sorted(
            self._skills,
            key=lambda skill: len(skill.keywords & query_terms),
            reverse=True,
        )
        return [skill for skill in ranked if skill.keywords & query_terms][:limit]

    def build_messages(self, query: str) -> list[Message]:
        skills = self.prefetch(query)
        if not skills:
            return []
        lines = [
            f"- {skill.name}: {skill.description} ({skill.path})"
            for skill in skills
        ]
        return [
            Message(
                role="system",
                content="Prefetched skills:\n" + "\n".join(lines),
                metadata={"source": "skill_prefetch"},
            )
        ]
