from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_runtime.schemas import Message


@dataclass(slots=True)
class PendingCacheEdits:
    trigger: str = "auto"
    deleted_tool_ids: list[str] = field(default_factory=list)
    baseline_deleted_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger": self.trigger,
            "deleted_tool_ids": list(self.deleted_tool_ids),
            "baseline_deleted_tokens": self.baseline_deleted_tokens,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "PendingCacheEdits | None":
        if not payload:
            return None
        return cls(
            trigger=str(payload.get("trigger", "auto")),
            deleted_tool_ids=[str(item) for item in payload.get("deleted_tool_ids", [])],
            baseline_deleted_tokens=int(payload.get("baseline_deleted_tokens", 0) or 0),
        )


@dataclass(slots=True)
class ContentReplacementRecord:
    kind: str
    tool_use_id: str
    replacement: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "tool_use_id": self.tool_use_id,
            "replacement": self.replacement,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ContentReplacementRecord":
        return cls(
            kind=str(payload.get("kind", "tool-result")),
            tool_use_id=str(payload.get("tool_use_id", "")),
            replacement=str(payload.get("replacement", "")),
        )


@dataclass(slots=True)
class ReadHistoryEntry:
    path: str
    content: str
    timestamp: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "content": self.content,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReadHistoryEntry":
        return cls(
            path=str(payload.get("path", "")),
            content=str(payload.get("content", "")),
            timestamp=float(payload.get("timestamp", 0.0) or 0.0),
        )


@dataclass(slots=True)
class InvokedSkillRecord:
    name: str
    path: str
    content: str
    invoked_at: float
    agent_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "content": self.content,
            "invoked_at": self.invoked_at,
            "agent_id": self.agent_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "InvokedSkillRecord":
        return cls(
            name=str(payload.get("name", "")),
            path=str(payload.get("path", "")),
            content=str(payload.get("content", "")),
            invoked_at=float(payload.get("invoked_at", 0.0) or 0.0),
            agent_id=str(payload["agent_id"]) if payload.get("agent_id") else None,
        )


@dataclass(slots=True)
class AsyncAgentRecord:
    task_id: str
    description: str
    status: str
    delta_summary: str = ""
    retrieved: bool = False
    agent_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "status": self.status,
            "delta_summary": self.delta_summary,
            "retrieved": self.retrieved,
            "agent_id": self.agent_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AsyncAgentRecord":
        return cls(
            task_id=str(payload.get("task_id", "")),
            description=str(payload.get("description", "")),
            status=str(payload.get("status", "")),
            delta_summary=str(payload.get("delta_summary", "")),
            retrieved=bool(payload.get("retrieved", False)),
            agent_id=str(payload["agent_id"]) if payload.get("agent_id") else None,
        )


@dataclass(slots=True)
class ArchivedSegment:
    path: str
    kind: str
    created_at: str
    message_count: int
    summary_uuid: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "created_at": self.created_at,
            "message_count": self.message_count,
            "summary_uuid": self.summary_uuid,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ArchivedSegment":
        return cls(
            path=str(payload.get("path", "")),
            kind=str(payload.get("kind", "compact")),
            created_at=str(payload.get("created_at", "")),
            message_count=int(payload.get("message_count", 0) or 0),
            summary_uuid=str(payload["summary_uuid"]) if payload.get("summary_uuid") else None,
        )


@dataclass(slots=True)
class TokenWarningState:
    percent_left: int
    is_above_warning_threshold: bool
    is_above_error_threshold: bool
    is_above_autocompact_threshold: bool
    is_at_blocking_limit: bool


@dataclass(slots=True)
class SnipResult:
    messages: list[Message]
    tokens_freed: int = 0
    boundary_message: Message | None = None
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MicrocompactInfo:
    pending_cache_edits: PendingCacheEdits | None = None
    compacted_tool_ids: list[str] = field(default_factory=list)
    cleared_attachment_uuids: list[str] = field(default_factory=list)
    tokens_saved: int = 0


@dataclass(slots=True)
class MicroCompactResult:
    messages: list[Message]
    boundary_message: Message | None = None
    compaction_info: MicrocompactInfo | None = None
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CompactionResult:
    boundary_marker: Message
    summary_messages: list[Message]
    attachments: list[Message] = field(default_factory=list)
    hook_results: list[Message] = field(default_factory=list)
    messages_to_keep: list[Message] = field(default_factory=list)
    pre_compact_token_count: int = 0
    post_compact_token_count: int = 0
    true_post_compact_token_count: int = 0
    compaction_usage: dict[str, int] | None = None
    transcript_path: str | None = None
    trigger: str = "auto"


@dataclass(slots=True)
class ContextSessionState:
    warning_suppressed: bool = False  # 是否已经抑制waning
    registered_tool_order: list[str] = field(default_factory=list)  # 记录tool注册顺序
    # 纪录已经删除的Tool ID
    deleted_tool_ids: set[str] = field(default_factory=set)
    # 待处理的缓存逻辑
    pending_cache_edits: PendingCacheEdits | None = None
    # 保存被固定的缓存编辑逻辑
    pinned_cache_edits: list[dict[str, Any]] = field(default_factory=list)
    # 记录已经处理过的Tool结果ID
    seen_tool_result_ids: set[str] = field(default_factory=set)
    # 记录Tool结果替代关系
    tool_result_replacements: dict[str, str] = field(default_factory=dict)
    session_memory_sections: list[str] = field(default_factory=list)
    last_summarized_message_uuid: str | None = None
    # 记录读取历史
    read_history: dict[str, ReadHistoryEntry] = field(default_factory=dict)
    # 记录已经调用的skill
    invoked_skills: list[InvokedSkillRecord] = field(default_factory=list)
    # 记录计划文件路径、内容
    plan_path: str | None = None
    plan_content: str | None = None
    plan_mode_active: bool = False
    # 记录异步agent
    async_agents: list[AsyncAgentRecord] = field(default_factory=list)
    archived_segments: list[ArchivedSegment] = field(default_factory=list)
    consecutive_autocompact_failures: int = 0
    post_compaction_pending: bool = False
    last_compaction_turn: int = 0
    last_compaction_id: str | None = None
    last_assistant_timestamp: str | None = None
    snipped_message_ids: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, Any]:
        return {
            "warning_suppressed": self.warning_suppressed,
            "registered_tool_order": list(self.registered_tool_order),
            "deleted_tool_ids": sorted(self.deleted_tool_ids),
            "pending_cache_edits": self.pending_cache_edits.to_dict()
            if self.pending_cache_edits
            else None,
            "pinned_cache_edits": list(self.pinned_cache_edits),
            "seen_tool_result_ids": sorted(self.seen_tool_result_ids),
            "tool_result_replacements": dict(self.tool_result_replacements),
            "session_memory_sections": list(self.session_memory_sections),
            "last_summarized_message_uuid": self.last_summarized_message_uuid,
            "read_history": {
                path: item.to_dict() for path, item in self.read_history.items()
            },
            "invoked_skills": [item.to_dict() for item in self.invoked_skills],
            "plan_path": self.plan_path,
            "plan_content": self.plan_content,
            "plan_mode_active": self.plan_mode_active,
            "async_agents": [item.to_dict() for item in self.async_agents],
            "archived_segments": [item.to_dict() for item in self.archived_segments],
            "consecutive_autocompact_failures": self.consecutive_autocompact_failures,
            "post_compaction_pending": self.post_compaction_pending,
            "last_compaction_turn": self.last_compaction_turn,
            "last_compaction_id": self.last_compaction_id,
            "last_assistant_timestamp": self.last_assistant_timestamp,
            "snipped_message_ids": sorted(self.snipped_message_ids),
        }

    # 类本身的方法，可以直接通弄过类名进行调用
    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ContextSessionState":
        if not payload:
            return cls()
        return cls(
            warning_suppressed=bool(payload.get("warning_suppressed", False)),
            registered_tool_order=[
                str(item) for item in payload.get("registered_tool_order", [])
            ],
            deleted_tool_ids={str(item) for item in payload.get("deleted_tool_ids", [])},
            pending_cache_edits=PendingCacheEdits.from_dict(
                payload.get("pending_cache_edits")
            ),
            pinned_cache_edits=list(payload.get("pinned_cache_edits", [])),
            seen_tool_result_ids={
                str(item) for item in payload.get("seen_tool_result_ids", [])
            },
            tool_result_replacements={
                str(key): str(value)
                for key, value in dict(payload.get("tool_result_replacements", {})).items()
            },
            session_memory_sections=[
                str(item) for item in payload.get("session_memory_sections", [])
            ],
            last_summarized_message_uuid=(
                str(payload["last_summarized_message_uuid"])
                if payload.get("last_summarized_message_uuid")
                else None
            ),
            read_history={
                str(path): ReadHistoryEntry.from_dict(item)
                for path, item in dict(payload.get("read_history", {})).items()
            },
            invoked_skills=[
                InvokedSkillRecord.from_dict(item)
                for item in payload.get("invoked_skills", [])
            ],
            plan_path=str(payload["plan_path"]) if payload.get("plan_path") else None,
            plan_content=(
                str(payload["plan_content"]) if payload.get("plan_content") else None
            ),
            plan_mode_active=bool(payload.get("plan_mode_active", False)),
            async_agents=[
                AsyncAgentRecord.from_dict(item)
                for item in payload.get("async_agents", [])
            ],
            archived_segments=[
                ArchivedSegment.from_dict(item)
                for item in payload.get("archived_segments", [])
            ],
            consecutive_autocompact_failures=int(
                payload.get("consecutive_autocompact_failures", 0) or 0
            ),
            post_compaction_pending=bool(payload.get("post_compaction_pending", False)),
            last_compaction_turn=int(payload.get("last_compaction_turn", 0) or 0),
            last_compaction_id=(
                str(payload["last_compaction_id"])
                if payload.get("last_compaction_id")
                else None
            ),
            last_assistant_timestamp=(
                str(payload["last_assistant_timestamp"])
                if payload.get("last_assistant_timestamp")
                else None
            ),
            snipped_message_ids={
                str(item) for item in payload.get("snipped_message_ids", [])
            },
        )
