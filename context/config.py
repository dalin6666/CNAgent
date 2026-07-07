from __future__ import annotations

from dataclasses import dataclass, field


def _default_compactable_tools() -> tuple[str, ...]:
    return (
        "Read",
        "read_file",
        "Bash",
        "PowerShell",
        "Grep",
        "Glob",
        "WebFetch",
        "WebSearch",
        "Edit",
        "Write",
    )


def _default_skip_persist_tools() -> frozenset[str]:
    return frozenset({"Read", "read_file"})


@dataclass(slots=True)
class ToolResultBudgetConfig:
    enabled: bool = True
    per_message_char_limit: int = 50_000
    preview_bytes: int = 2_000
    default_max_result_chars: int = 50_000
    skip_persist_tool_names: frozenset[str] = field(
        default_factory=_default_skip_persist_tools
    )


@dataclass(slots=True)
class SnipConfig:
    enabled: bool = True
    trigger_message_count: int = 48
    protected_tail_messages: int = 12
    protected_head_messages: int = 2
    min_messages_to_snip: int = 6


@dataclass(slots=True)
class MicroCompactConfig:
    enabled: bool = True
    cached_enabled: bool = True
    time_based_enabled: bool = True
    cached_trigger_threshold: int = 12
    cached_keep_recent: int = 4
    time_gap_threshold_minutes: int = 60
    time_based_keep_recent: int = 5
    compactable_tool_names: tuple[str, ...] = field(
        default_factory=_default_compactable_tools
    )


@dataclass(slots=True)
class SessionMemoryCompactConfig:
    enabled: bool = True
    min_tokens: int = 10_000
    min_text_messages: int = 5
    max_tokens: int = 40_000


@dataclass(slots=True)
class AutoCompactConfig:
    enabled: bool = True
    autocompact_buffer_tokens: int = 13_000
    warning_buffer_tokens: int = 20_000
    error_buffer_tokens: int = 20_000
    manual_compact_buffer_tokens: int = 3_000
    max_consecutive_failures: int = 3
    summary_keep_tail_messages: int = 10
    partial_summary_keep_tail_messages: int = 6


@dataclass(slots=True)
class ReactiveCompactConfig:
    enabled: bool = True
    strip_attachment_messages_first: bool = True
    retry_with_truncated_head: bool = True
    max_truncated_head_messages: int = 24


@dataclass(slots=True)
class PostCompactRestoreConfig:
    max_files_to_restore: int = 5
    max_tokens_per_file: int = 5_000
    file_restore_token_budget: int = 50_000
    max_tokens_per_skill: int = 5_000
    skill_restore_token_budget: int = 25_000

# 上下文配置
@dataclass(slots=True)
class ContextConfig:
    enabled: bool = True  # 是否启用
    storage_subdir: str = "context"
    transcript_subdir: str = "transcripts"
    summary_subdir: str = "summaries"
    tool_result_subdir: str = "tool-results"
    snip: SnipConfig = field(default_factory=SnipConfig)
    microcompact: MicroCompactConfig = field(default_factory=MicroCompactConfig)
    session_memory: SessionMemoryCompactConfig = field(
        default_factory=SessionMemoryCompactConfig
    )
    tool_result_budget: ToolResultBudgetConfig = field(
        default_factory=ToolResultBudgetConfig
    )
    auto: AutoCompactConfig = field(default_factory=AutoCompactConfig)
    reactive: ReactiveCompactConfig = field(default_factory=ReactiveCompactConfig)
    restore: PostCompactRestoreConfig = field(
        default_factory=PostCompactRestoreConfig
    )
