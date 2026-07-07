from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .._runtime import SimpleTool, ToolUseContext


def _candidate_skill_roots(cwd: str | None) -> list[Path]:
    roots: list[Path] = []
    if cwd:
        roots.append(Path(cwd) / 'skills')
    codex_home = os.environ.get('CODEX_HOME')
    if codex_home:
        roots.append(Path(codex_home) / 'skills')
    roots.append(Path.home() / '.codex' / 'skills')
    return roots


def _find_skill(skill_name: str, cwd: str | None) -> Path | None:
    for root in _candidate_skill_roots(cwd):
        if not root.exists():
            continue
        for candidate in root.rglob('SKILL.md'):
            if candidate.parent.name == skill_name or skill_name.casefold() in str(candidate.parent).casefold():
                return candidate
    return None


def _call(skill_name: str, args: str | None = None, toolUseContext: ToolUseContext | None = None, **_kwargs: Any) -> dict[str, Any]:
    cwd = toolUseContext.options.cwd if toolUseContext else None
    skill_file = _find_skill(skill_name, cwd)
    if skill_file is None:
        return {'data': {'found': False, 'skill_name': skill_name, 'message': 'Skill not found in known skill directories.'}}
    content = skill_file.read_text(encoding='utf-8', errors='replace')
    preview = content[:4000]
    return {'data': {'found': True, 'skill_name': skill_name, 'path': str(skill_file), 'preview': preview, 'args': args}}


SkillTool = SimpleTool(
    name='Skill',
    description_text='Locate and read Codex skill definitions from local skill directories.',
    prompt_text='Use when a workflow needs to inspect or surface a SKILL.md file.',
    call_handler=_call,
    input_schema={'skill_name': 'skill directory name', 'args': 'optional skill arguments'},
    output_schema={'found': 'whether the skill was found', 'preview': 'skill preview text'},
    user_facing_name='Skill',
)
