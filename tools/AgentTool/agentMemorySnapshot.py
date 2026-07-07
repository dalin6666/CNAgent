from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .agentMemory import AgentMemoryScope, getAgentMemoryDir


SNAPSHOT_BASE = "agent-memory-snapshots"
SNAPSHOT_JSON = "snapshot.json"
SYNCED_JSON = ".snapshot-synced.json"


@dataclass
class SnapshotCheckResult:
    action: str
    snapshotTimestamp: str | None = None


def getSnapshotDirForAgent(agent_type: str) -> str:
    return str(Path.cwd() / ".claude" / SNAPSHOT_BASE / agent_type)


def _snapshot_json_path(agent_type: str) -> Path:
    return Path(getSnapshotDirForAgent(agent_type)) / SNAPSHOT_JSON


def _synced_json_path(agent_type: str, scope: AgentMemoryScope) -> Path:
    return Path(getAgentMemoryDir(agent_type, scope)) / SYNCED_JSON


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _copy_snapshot_to_local(agent_type: str, scope: AgentMemoryScope) -> None:
    snapshot_dir = Path(getSnapshotDirForAgent(agent_type))
    local_dir = Path(getAgentMemoryDir(agent_type, scope))
    local_dir.mkdir(parents=True, exist_ok=True)
    if not snapshot_dir.exists():
        return
    for child in snapshot_dir.iterdir():
        if child.is_file() and child.name != SNAPSHOT_JSON:
            (local_dir / child.name).write_text(child.read_text(encoding="utf-8"), encoding="utf-8")


def _save_synced_meta(agent_type: str, scope: AgentMemoryScope, snapshot_timestamp: str) -> None:
    synced = _synced_json_path(agent_type, scope)
    synced.parent.mkdir(parents=True, exist_ok=True)
    synced.write_text(json.dumps({"syncedFrom": snapshot_timestamp}, indent=2), encoding="utf-8")


def checkAgentMemorySnapshot(agent_type: str, scope: AgentMemoryScope) -> SnapshotCheckResult:
    snapshot = _read_json(_snapshot_json_path(agent_type))
    if not snapshot or not snapshot.get("updatedAt"):
        return SnapshotCheckResult(action="none")
    local_dir = Path(getAgentMemoryDir(agent_type, scope))
    has_local_memory = local_dir.exists() and any(
        child.is_file() and child.suffix == ".md" for child in local_dir.iterdir()
    )
    if not has_local_memory:
        return SnapshotCheckResult("initialize", str(snapshot["updatedAt"]))
    synced = _read_json(_synced_json_path(agent_type, scope))
    if not synced or snapshot["updatedAt"] > synced.get("syncedFrom", ""):
        return SnapshotCheckResult("prompt-update", str(snapshot["updatedAt"]))
    return SnapshotCheckResult(action="none")


def initializeFromSnapshot(agent_type: str, scope: AgentMemoryScope, snapshot_timestamp: str) -> None:
    _copy_snapshot_to_local(agent_type, scope)
    _save_synced_meta(agent_type, scope, snapshot_timestamp)


def replaceFromSnapshot(agent_type: str, scope: AgentMemoryScope, snapshot_timestamp: str) -> None:
    local_dir = Path(getAgentMemoryDir(agent_type, scope))
    if local_dir.exists():
        for child in local_dir.iterdir():
            if child.is_file() and child.suffix == ".md":
                child.unlink()
    _copy_snapshot_to_local(agent_type, scope)
    _save_synced_meta(agent_type, scope, snapshot_timestamp)


def markSnapshotSynced(agent_type: str, scope: AgentMemoryScope, snapshot_timestamp: str) -> None:
    _save_synced_meta(agent_type, scope, snapshot_timestamp)

