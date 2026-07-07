from __future__ import annotations

import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any

from ._runtime import STATE_ROOT, create_id, ensure_directory


VALID_WORKTREE_SLUG_SEGMENT = re.compile(r"^[a-zA-Z0-9._-]+$")
MAX_WORKTREE_SLUG_LENGTH = 64
MAX_PLAN_SLUG_RETRIES = 10

_WORD_ADJECTIVES = (
    "amber",
    "brisk",
    "calm",
    "clear",
    "ember",
    "keen",
    "lucky",
    "mellow",
    "nimble",
    "quiet",
    "steady",
    "swift",
)

_WORD_NOUNS = (
    "brook",
    "cedar",
    "comet",
    "field",
    "harbor",
    "meadow",
    "otter",
    "ridge",
    "sparrow",
    "stone",
    "stream",
    "willow",
)


def _session_bucket(app_state: Any) -> dict[str, Any]:
    metadata = getattr(app_state, "metadata", None)
    if not isinstance(metadata, dict):
        metadata = {}
        app_state.metadata = metadata
    bucket = metadata.get("session_state")
    if not isinstance(bucket, dict):
        bucket = {}
        metadata["session_state"] = bucket
    return bucket


def _path_within(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _generate_word_slug() -> str:
    token = uuid.uuid4().hex
    adjective = _WORD_ADJECTIVES[int(token[:2], 16) % len(_WORD_ADJECTIVES)]
    noun = _WORD_NOUNS[int(token[2:4], 16) % len(_WORD_NOUNS)]
    return f"{adjective}-{noun}-{token[4:8]}"


def get_session_id(app_state: Any) -> str:
    bucket = _session_bucket(app_state)
    session_id = bucket.get("session_id")
    if isinstance(session_id, str) and session_id:
        return session_id
    session_id = str(uuid.uuid4())
    bucket["session_id"] = session_id
    return session_id


def get_project_root(app_state: Any, cwd: str | None = None) -> str:
    bucket = _session_bucket(app_state)
    project_root = bucket.get("project_root")
    if isinstance(project_root, str) and project_root:
        return project_root
    resolved = str(Path(cwd or os.getcwd()).resolve())
    bucket["project_root"] = resolved
    return resolved


def set_project_root(app_state: Any, cwd: str) -> str:
    resolved = str(Path(cwd).resolve())
    _session_bucket(app_state)["project_root"] = resolved
    return resolved


def get_original_cwd(app_state: Any, cwd: str | None = None) -> str:
    bucket = _session_bucket(app_state)
    original_cwd = bucket.get("original_cwd")
    if isinstance(original_cwd, str) and original_cwd:
        return original_cwd
    resolved = str(Path(cwd or os.getcwd()).resolve())
    bucket["original_cwd"] = resolved
    return resolved


def set_original_cwd(app_state: Any, cwd: str) -> str:
    resolved = str(Path(cwd).resolve())
    _session_bucket(app_state)["original_cwd"] = resolved
    return resolved


def get_plans_directory(app_state: Any, cwd: str | None = None) -> str:
    settings = getattr(app_state, "settings", None) or {}
    configured = settings.get("plansDirectory")
    if isinstance(configured, str) and configured.strip():
        project_root = Path(get_project_root(app_state, cwd)).resolve()
        configured_path = Path(configured).expanduser()
        candidate = (
            configured_path.resolve()
            if configured_path.is_absolute()
            else (project_root / configured_path).resolve()
        )
        if _path_within(candidate, project_root):
            return str(ensure_directory(candidate))
    return str(ensure_directory(STATE_ROOT / "plans"))


def get_plan_slug(app_state: Any) -> str:
    bucket = _session_bucket(app_state)
    session_id = get_session_id(app_state)
    cache = bucket.get("plan_slug_cache")
    if not isinstance(cache, dict):
        cache = {}
        bucket["plan_slug_cache"] = cache
    slug = cache.get(session_id)
    if isinstance(slug, str) and slug:
        return slug

    plans_dir = Path(get_plans_directory(app_state))
    candidate = ""
    for _ in range(MAX_PLAN_SLUG_RETRIES):
        candidate = _generate_word_slug()
        if not (plans_dir / f"{candidate}.md").exists():
            break
    if not candidate:
        candidate = f"plan-{uuid.uuid4().hex[:8]}"
    cache[session_id] = candidate
    return candidate


def get_plan_file_path(app_state: Any, agent_id: str | None = None) -> str:
    slug = get_plan_slug(app_state)
    if agent_id:
        filename = f"{slug}-agent-{agent_id}.md"
    else:
        filename = f"{slug}.md"
    return str(Path(get_plans_directory(app_state)) / filename)


def read_plan(app_state: Any, agent_id: str | None = None) -> str | None:
    path = Path(get_plan_file_path(app_state, agent_id))
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def write_plan(app_state: Any, content: str, agent_id: str | None = None) -> str:
    path = Path(get_plan_file_path(app_state, agent_id))
    ensure_directory(path.parent)
    path.write_text(content, encoding="utf-8")
    bucket = _session_bucket(app_state)
    snapshots = bucket.get("file_snapshots")
    if not isinstance(snapshots, dict):
        snapshots = {}
        bucket["file_snapshots"] = snapshots
    snapshots["plan"] = {"path": str(path), "content": content}
    return str(path)


def validate_worktree_slug(slug: str) -> None:
    if len(slug) > MAX_WORKTREE_SLUG_LENGTH:
        raise ValueError(
            "Invalid worktree name: must be "
            f"{MAX_WORKTREE_SLUG_LENGTH} characters or fewer (got {len(slug)})"
        )
    for segment in slug.split("/"):
        if segment in {".", ".."}:
            raise ValueError(
                f'Invalid worktree name "{slug}": must not contain "." or ".." path segments'
            )
        if not VALID_WORKTREE_SLUG_SEGMENT.fullmatch(segment):
            raise ValueError(
                f'Invalid worktree name "{slug}": each "/"-separated segment must be '
                "non-empty and contain only letters, digits, dots, underscores, and dashes"
            )


def flatten_worktree_slug(slug: str) -> str:
    return slug.replace("/", "+")


def worktree_branch_name(slug: str) -> str:
    return f"worktree-{flatten_worktree_slug(slug)}"


def worktree_path_for(repo_root: str, slug: str) -> str:
    return str(Path(repo_root) / ".claude" / "worktrees" / flatten_worktree_slug(slug))


def find_git_root(start_path: str) -> str | None:
    current = Path(start_path).resolve()
    if current.is_file():
        current = current.parent
    while True:
        git_path = current / ".git"
        if git_path.is_dir() or git_path.is_file():
            return str(current)
        if current.parent == current:
            return None
        current = current.parent


def _read_gitdir_pointer(git_root: str) -> Path | None:
    git_pointer = Path(git_root) / ".git"
    if not git_pointer.is_file():
        return None
    try:
        content = git_pointer.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not content.startswith("gitdir:"):
        return None
    return (Path(git_root) / content.split(":", 1)[1].strip()).resolve()


def find_canonical_git_root(start_path: str) -> str | None:
    git_root = find_git_root(start_path)
    if git_root is None:
        return None
    gitdir = _read_gitdir_pointer(git_root)
    if gitdir is None:
        return git_root
    common_dir_file = gitdir / "commondir"
    if not common_dir_file.exists():
        return git_root
    try:
        common_dir = (gitdir / common_dir_file.read_text(encoding="utf-8").strip()).resolve()
    except OSError:
        return git_root
    if common_dir.name == ".git":
        return str(common_dir.parent)
    return str(common_dir)


def _run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )


def _git_head(cwd: str) -> str | None:
    result = _run_git(["rev-parse", "HEAD"], cwd)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _git_branch(cwd: str) -> str | None:
    result = _run_git(["branch", "--show-current"], cwd)
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return branch or None


def get_current_worktree_session(app_state: Any) -> dict[str, Any] | None:
    session = _session_bucket(app_state).get("current_worktree_session")
    return dict(session) if isinstance(session, dict) else None


def save_worktree_state(
    app_state: Any,
    worktree_session: dict[str, Any] | None,
) -> dict[str, Any] | None:
    bucket = _session_bucket(app_state)
    if worktree_session is None:
        bucket["current_worktree_session"] = None
        bucket["persisted_worktree_session"] = None
        bucket["current_worktree_session_id"] = None
        return None

    stripped = {
        "id": worktree_session.get("id"),
        "originalCwd": worktree_session.get("originalCwd"),
        "worktreePath": worktree_session.get("worktreePath"),
        "worktreeName": worktree_session.get("worktreeName"),
        "worktreeBranch": worktree_session.get("worktreeBranch"),
        "originalBranch": worktree_session.get("originalBranch"),
        "originalHeadCommit": worktree_session.get("originalHeadCommit"),
        "sessionId": worktree_session.get("sessionId"),
        "tmuxSessionName": worktree_session.get("tmuxSessionName"),
        "hookBased": worktree_session.get("hookBased"),
        "active": worktree_session.get("active", True),
    }
    bucket["current_worktree_session"] = dict(stripped)
    bucket["persisted_worktree_session"] = dict(stripped)
    bucket["current_worktree_session_id"] = stripped.get("id")
    return stripped


def create_worktree_for_session(
    app_state: Any,
    session_id: str,
    slug: str,
    cwd: str,
) -> dict[str, Any]:
    validate_worktree_slug(slug)
    original_cwd = str(Path(cwd).resolve())
    git_root = find_git_root(original_cwd)
    if not git_root:
        raise RuntimeError(
            "Cannot create a worktree: not in a git repository. "
            "The Python port currently supports git-backed worktrees only."
        )

    worktree_path = worktree_path_for(git_root, slug)
    worktree_branch = worktree_branch_name(slug)
    head_commit = _git_head(worktree_path) if Path(worktree_path).exists() else None

    if head_commit is None:
        ensure_directory(Path(worktree_path).parent)
        create_result = _run_git(
            ["worktree", "add", "-B", worktree_branch, worktree_path, "HEAD"],
            git_root,
        )
        if create_result.returncode != 0:
            message = create_result.stderr.strip() or create_result.stdout.strip()
            raise RuntimeError(f"Failed to create worktree: {message or 'git worktree add failed'}")
        head_commit = _git_head(worktree_path)

    if head_commit is None:
        raise RuntimeError("Worktree was created but HEAD could not be resolved.")

    branch = _git_branch(worktree_path) or worktree_branch
    worktree_id = create_id("worktree_")
    session = {
        "id": worktree_id,
        "originalCwd": original_cwd,
        "worktreePath": worktree_path,
        "worktreeName": slug,
        "worktreeBranch": branch,
        "originalBranch": _git_branch(git_root),
        "originalHeadCommit": head_commit,
        "sessionId": session_id,
        "tmuxSessionName": None,
        "hookBased": False,
        "active": True,
    }
    app_state.worktrees[worktree_id] = dict(session)
    save_worktree_state(app_state, session)
    return session


__all__ = [
    "create_worktree_for_session",
    "find_canonical_git_root",
    "find_git_root",
    "get_current_worktree_session",
    "get_original_cwd",
    "get_plan_file_path",
    "get_plan_slug",
    "get_plans_directory",
    "get_project_root",
    "get_session_id",
    "read_plan",
    "save_worktree_state",
    "set_original_cwd",
    "set_project_root",
    "validate_worktree_slug",
    "worktree_branch_name",
    "worktree_path_for",
    "write_plan",
]
