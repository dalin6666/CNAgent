## Context Package

This package ports the context-management and compaction ideas from the
referenced `_context_compaction_sources` materials into the Python runtime.

### Source-to-module mapping

- `INDEX.md` level 1 snip / history trimming
  - `context/snip.py`
- `INDEX.md` level 2 microcompact / cache-edit style tool result shrinking
  - `context/microcompact.py`
  - `context/tool_results.py`
- `INDEX.md` level 3 autocompact / full summary compaction
  - `context/autocompact.py`
  - `context/compaction.py`
  - `context/summary.py`
  - `context/prompt.py`
- `INDEX.md` level 4 reactive compact / prompt-too-long recovery
  - `context/reactive.py`
- `INDEX.md` support files and state
  - `context/messages.py`
  - `context/storage.py`
  - `context/state.py`
  - `context/types.py`
- Runtime orchestration entrypoint
  - `context/manager.py`

### Logic covered

- Compact-boundary messages and preserved-tail metadata
- Per-message tool result budget enforcement with persisted previews
- History snip projection
- Cached-style and time-based microcompact behavior
- Session-memory-backed compaction
- Full conversation compaction with transcript archival
- Post-compact restoration for files, plans, invoked skills, and async agents
- Reactive recovery for prompt-too-long and media-size errors
- Integration with `agent_runtime` request preparation and retry flow

### Runtime integration points

- `agent_runtime/config.py`
  - adds `RuntimeConfig.context_config`
- `agent_runtime/schemas.py`
  - adds message ids, timestamps, subtypes, and session `context_state`
- `agent_runtime/runtime/compression.py`
  - delegates to `ContextManager`
- `agent_runtime/runtime/engine.py`
  - routes tool results and provider failures through the context pipeline
