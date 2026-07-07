# Agent Runtime Tool Catalog

## Native Runtime Tools

- `echo` -> `lookup`
- `glob_search` -> `read`
- `read_file` -> `read`

## Adapted Legacy Tools

### `agent`

- `Agent`
  Alias: `Task`

### `interactive`

- `AskUserQuestion`

### `exec`

- `Bash`
- `PowerShell`
- `Sleep`

### `lookup`

- `Brief`
- `Skill`
- `WebFetch`
- `WebSearch`

### `mcp`

- `ListMcpResources`
- `MCP`
- `McpAuth`
- `ReadMcpResource`

### `read`

- `Glob`
- `Grep`
- `LSP`
- `Read`
- `TaskGet`
- `TaskList`
- `TaskOutput`
- `ToolSearch`

### `write`

- `Edit`
- `NotebookEdit`
- `Write`

### `state`

- `Config`
- `EnterPlanMode`
- `EnterWorktree`
- `ExitPlanMode`
- `ExitWorktree`
- `SendMessage`
- `SyntheticOutput`
- `TaskCreate`
- `TaskStop`
- `TaskUpdate`
- `TeamCreate`
- `TeamDelete`
- `TodoWrite`

### `automation`

- `CronCreate`
- `CronDelete`
- `CronList`
- `RemoteTrigger`

## Adaptation Notes

- All top-level `tools.__all__` exports with a `call()` entrypoint are registered through `agent_runtime/tools/legacy_adapter.py`.
- Legacy aliases are preserved when present.
- Legacy input/output schemas are exposed through the new registry.
- Legacy tool-specific permission decisions are bridged into the new runtime.
- Read/write path restrictions are still enforced by the legacy tool logic under the adapter.
