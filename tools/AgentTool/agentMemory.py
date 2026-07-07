from __future__ import annotations

import os
from pathlib import Path


AgentMemoryScope = str


def _project_root() -> Path:
    return Path.cwd()


def _memory_base_dir() -> Path:
    env_override = os.environ.get("CLAUDE_CODE_MEMORY_BASE_DIR")
    return Path(env_override) if env_override else Path.home() / ".claude"


def sanitizeAgentTypeForPath(agent_type: str) -> str:
    return agent_type.replace(":", "-")


def _sanitize_path(value: str) -> str:
    return value.replace(":", "_").replace("\\", "_").replace("/", "_")


def _local_agent_memory_dir(dir_name: str) -> Path:
    remote_base = os.environ.get("CLAUDE_CODE_REMOTE_MEMORY_DIR")
    if remote_base:
        project = _sanitize_path(str(_project_root().resolve()))
        return Path(remote_base) / "projects" / project / "agent-memory-local" / dir_name
    return _project_root() / ".claude" / "agent-memory-local" / dir_name


def getAgentMemoryDir(agent_type: str, scope: AgentMemoryScope) -> str:
    dir_name = sanitizeAgentTypeForPath(agent_type)
    if scope == "project":
        return str(_project_root() / ".claude" / "agent-memory" / dir_name)
    if scope == "local":
        return str(_local_agent_memory_dir(dir_name))
    return str(_memory_base_dir() / "agent-memory" / dir_name)


def isAgentMemoryPath(absolute_path: str) -> bool:
    normalized = Path(absolute_path).resolve()
    user_memory = (_memory_base_dir() / "agent-memory").resolve()
    project_memory = (_project_root() / ".claude" / "agent-memory").resolve()
    local_memory = (_project_root() / ".claude" / "agent-memory-local").resolve()
    candidates = [user_memory, project_memory, local_memory]
    remote_base = os.environ.get("CLAUDE_CODE_REMOTE_MEMORY_DIR")
    if remote_base:
        candidates.append((Path(remote_base) / "projects").resolve())
    return any(str(normalized).startswith(str(candidate)) for candidate in candidates)


def getAgentMemoryEntrypoint(agent_type: str, scope: AgentMemoryScope) -> str:
    return str(Path(getAgentMemoryDir(agent_type, scope)) / "MEMORY.md")


def getMemoryScopeDisplay(memory: AgentMemoryScope | None) -> str:
    if memory == "user":
        return f"User ({_memory_base_dir() / 'agent-memory'})"
    if memory == "project":
        return "Project (.claude/agent-memory/)"
    if memory == "local":
        return f"Local ({_local_agent_memory_dir('...')})"
    return "None"


def loadAgentMemoryPrompt(agent_type: str, scope: AgentMemoryScope) -> str:
    if scope == "user":
        scope_note = "- Since this memory is user-scope, keep learnings general."
    elif scope == "project":
        scope_note = "- Since this memory is project-scope, tailor memories to this project."
    else:
        scope_note = "- Since this memory is local-scope, tailor memories to this machine."
    memory_dir = Path(getAgentMemoryDir(agent_type, scope))
    memory_dir.mkdir(parents=True, exist_ok=True)
    entrypoint = memory_dir / "MEMORY.md"
    if not entrypoint.exists():
        entrypoint.write_text("", encoding="utf-8")
    existing = entrypoint.read_text(encoding="utf-8")
    extra = os.environ.get("CLAUDE_COWORK_MEMORY_EXTRA_GUIDELINES", "").strip()
    notes = "\n".join(filter(None, [scope_note, extra]))
    return (
        "Persistent Agent Memory\n"
        f"Directory: {memory_dir}\n"
        f"{notes}\n\n"
        "Current memory contents:\n"
        f"{existing}"
    ).strip()

