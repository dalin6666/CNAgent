from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(limit - 3, 0)] + "..."


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class Attachment:
    path: str
    description: str | None = None


@dataclass(slots=True)
class FileSnapshot:
    path: str
    mtime_ns: int
    size: int

    @classmethod
    def from_path(cls, path: str) -> "FileSnapshot | None":
        try:
            stat = os.stat(path)
        except OSError:
            return None
        return cls(path=path, mtime_ns=stat.st_mtime_ns, size=stat.st_size)

# 面对类定义时，有些可变默认值（不同实例对象不同的成员变量），需要使用field(default_factory=...)
@dataclass(slots=True)
class Message:
    role: str
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    # 处理可变默认值写法：default_factory=dict
    metadata: dict[str, Any] = field(default_factory=dict)
    folded: bool = False # 是否折叠，消息压缩
    # default_factory：每创建一个新的message就执行一次_now_iso,否则可能只在类定义时执行一次
    timestamp: str = field(default_factory=_now_iso) 
    uuid: str = field(default_factory=lambda: uuid.uuid4().hex)
    subtype: str | None = None   
    is_meta: bool = False

    # 只保留限制数limit之内得数
    def short(self, limit: int = 120) -> str:
        return _shorten(self.content.replace("\n", " "), limit)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "name": self.name,
            "tool_call_id": self.tool_call_id,
            "metadata": dict(self.metadata),
            "folded": self.folded,
            "timestamp": self.timestamp,
            "uuid": self.uuid,
            "subtype": self.subtype,
            "is_meta": self.is_meta,
        }

    # 类方法，表示属于类本身，不属于某个实例对象
    # 用于从dict中回复一个实例message对象
    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Message":
        return cls(
            role=str(payload.get("role", "system")),
            content=str(payload.get("content", "")),
            name=str(payload["name"]) if payload.get("name") else None,
            tool_call_id=(
                str(payload["tool_call_id"]) if payload.get("tool_call_id") else None
            ),
            metadata=dict(payload.get("metadata", {})),
            folded=bool(payload.get("folded", False)),
            timestamp=str(payload.get("timestamp", _now_iso())),
            uuid=str(payload.get("uuid", uuid.uuid4().hex)),
            subtype=str(payload["subtype"]) if payload.get("subtype") else None,
            is_meta=bool(payload.get("is_meta", False)),
        )


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolResult:
    tool_call_id: str
    name: str
    output: Any
    is_error: bool = False
    duration_ms: float = 0.0
    summary: str | None = None

    # 将ToolResult做成一个json字符串
    def as_message_content(self) -> str:
        payload = {
            "tool": self.name,
            "tool_call_id": self.tool_call_id,
            "is_error": self.is_error,
            "summary": self.summary,
            "output": self.output,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


@dataclass(slots=True)
class ToolStreamDelta:
    text: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class UsageSnapshot:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    def merge(self, other: "UsageSnapshot | None") -> None:
        if other is None:
            return
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.total_tokens += other.total_tokens


@dataclass(slots=True)
class ModelRequest:
    messages: list[Message]
    available_tools: list[dict[str, Any]]
    model: str
    system_prompt: str
    max_output_tokens: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ModelChunk:
    kind: str
    text: str = ""
    tool_call: ToolCall | None = None
    usage: UsageSnapshot | None = None
    stop_reason: str | None = None
    error: str | None = None


@dataclass(slots=True)
class BudgetStatus:
    estimated_prompt_tokens: int
    available_input_tokens: int
    needs_compression: bool
    overflow_tokens: int = 0


@dataclass(slots=True)
class SessionState:
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    messages: list[Message] = field(default_factory=list)
    # 当前session的token使用情况
    usage: UsageSnapshot = field(default_factory=UsageSnapshot)
    turn_count: int = 0
    compression_level: int = 0
    continuation_count: int = 0
    active_model: str | None = None
    file_snapshots: dict[str, FileSnapshot] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    context_state: dict[str, Any] = field(default_factory=dict)
    finished: bool = False
