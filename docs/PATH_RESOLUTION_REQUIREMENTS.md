# `resolve_path` 工作目录边界约束需求报告

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 文档名称 | `resolve_path` 工作目录边界约束需求报告 |
| 所属模块 | `agent_runtime/tools/base.py` |
| 需求类型 | 安全性与路径访问控制 |
| 当前状态 | 已实施，待完整测试环境验证 |
| 编写日期 | 2026-07-19 |

## 2. 需求背景

`ToolRuntimeContext.resolve_path()` 当前只负责拼接并规范化路径：

```python
def resolve_path(self, path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return Path(self.working_directory, candidate).resolve()
```

该实现没有校验规范化后的结果是否仍位于工作目录内，因此存在以下越界方式：

1. 传入工作目录外部的绝对路径时，函数会直接返回该路径。
2. 传入 `..\\secret.txt` 或 `../secret.txt` 时，`resolve()` 会将路径解析到工作目录之外。
3. 工作目录内的符号链接如果指向外部目录，解析后的路径也可能越过工作目录边界。

当前实现会影响至少以下调用链：

- `agent_runtime/tools/builtin_read_file.py`：读取工作目录外的文件。
- `agent_runtime/tools/builtin_glob_search.py`：从工作目录外开始递归搜索。
- `ToolRuntimeContext.file_snapshot()` 和 `remember_file_snapshot()`：对外部文件建立快照。
- `ToolRuntimeContext.set_working_directory()`：当前目录是可变状态，不能天然作为稳定的安全边界。

## 3. 需求目标

建立“工作区根目录”边界，使运行时工具解析出的所有路径都满足以下不变量：

> 规范化并解析符号链接后的目标路径，必须是工作区根目录本身，或位于其子目录中。

同时保持现有正常用法不变：

- 工作目录内的相对路径继续按当前 `working_directory` 解析。
- 工作目录内的绝对路径可以继续使用。
- `.`、工作区根目录和其子目录仍然可以访问。
- 越界路径在实际文件读取、搜索或写入前被拒绝。

## 4. 功能需求

### FR-01：增加不可变的工作区根目录

`ToolRuntimeContext` 应增加 `workspace_root` 概念，作为本次运行的安全边界。

- `workspace_root` 应在创建运行时上下文时由 `AgentRuntime.config.working_directory` 显式传入。
- `workspace_root` 应在初始化时完成 `expanduser()` 和 `resolve(strict=False)` 规范化。
- 后续 `working_directory` 可以在工作区根目录下切换，但不得改变 `workspace_root`。
- 不应仅使用可变的 `working_directory` 作为边界，否则切换当前目录后边界可能发生漂移。
- 为保持兼容，字段可以暂时允许缺省并以创建时的 `working_directory` 初始化；运行时引擎必须显式传入根目录，不能依赖该兼容默认值。

### FR-02：统一解析相对路径和绝对路径

`resolve_path(path)` 应按以下规则解析：

1. 先对输入执行用户目录展开，例如 `~`。
2. 相对路径以当前 `working_directory` 为基准。
3. 绝对路径直接作为候选路径，但仍必须经过工作区边界校验。
4. 对候选路径执行 `resolve(strict=False)`，以处理 `.`、`..` 和已有符号链接。
5. 校验解析结果是否位于 `workspace_root` 内。
6. 校验通过后返回规范化后的 `Path`；否则抛出路径越界异常。

推荐的核心实现形态如下，具体异常类型可按项目约定落地：

```python
def resolve_path(self, path: str | Path) -> Path:
    root = Path(self.workspace_root).expanduser().resolve(strict=False)
    current = Path(self.working_directory).expanduser().resolve(strict=False)
    raw = Path(path).expanduser()

    candidate = raw if raw.is_absolute() else current / raw
    resolved = candidate.resolve(strict=False)

    if not resolved.is_relative_to(root):
        raise ValueError(
            f"Path is outside the workspace: {path!s}. "
            f"Workspace root: {root}"
        )
    return resolved
```

> 说明：项目要求 Python 3.10 及以上，`Path.is_relative_to()` 可以用于边界判断。不要通过字符串前缀判断路径是否在工作目录内，否则会把 `D:\\workspace-old` 错误地当成 `D:\\workspace` 的子路径。

### FR-03：限制工作目录切换

`set_working_directory(path)` 应继续复用 `resolve_path()`，并且只有解析结果位于 `workspace_root` 内时才更新：

- 切换成功后更新 `working_directory` 和 `session.metadata["working_directory"]`。
- 越界切换失败时，不得修改当前目录或会话元数据。
- `set_working_directory("..")` 在当前目录不是根目录时，只允许切换到仍处于 `workspace_root` 内的目录；如果会越过根目录则拒绝。
- 是否额外要求目标存在且为目录，属于独立需求；本次边界修复不强制改变现有的存在性语义。

### FR-04：校验会话目录来源

运行时每次构造 `ToolRuntimeContext` 时，必须以配置中的工作区根目录作为 `workspace_root`，并校验会话元数据中的当前目录：

```python
context = ToolRuntimeContext(
    session=session,
    working_directory=self._session_working_directory(session),
    workspace_root=self.config.working_directory,
    config=self.config,
    telemetry=telemetry,
    interrupt_controller=self.interrupt_controller,
)
```

如果 `session.metadata["working_directory"]` 被外部修改为工作区外路径，应在工具执行前拒绝，不能让该路径进入旧工具适配层或文件系统操作。

### FR-05：统一错误行为

路径越界时应抛出明确的异常。推荐新增语义化异常，例如 `PathOutsideWorkspaceError(ValueError)`；如果暂不新增异常，至少保持抛出 `ValueError`，以兼容当前工具执行器的错误处理流程。

错误应满足：

- 明确说明路径超出工作区范围。
- 包含工作区根目录，便于定位配置问题。
- 不应在日志或工具结果中暴露不必要的敏感文件内容。
- 由现有工具执行器转换为 `ToolResult(is_error=True)`，不得执行后续读取、遍历或写入动作。

## 5. 非功能需求

### NFR-01：跨平台

实现必须兼容 Windows 和 POSIX 路径，包括：

- Windows 盘符和大小写不敏感比较。
- Windows `\\` 与 POSIX `/` 分隔符。
- 相对路径、绝对路径和用户目录展开。
- 工作区内符号链接与指向工作区外的符号链接。

### NFR-02：边界校验优先于文件操作

所有路径边界校验必须发生在 `read_bytes()`、`os.walk()` 或任何其他实际文件系统操作之前。`resolve(strict=False)` 可以用于解析路径，但不得因为目标不存在而绕过边界校验。

### NFR-03：安全边界稳定

会话当前目录变化、旧工具同步目录、相对路径中的 `..` 或绝对路径输入都不得改变本次运行的 `workspace_root`。

## 6. 影响范围

### 必须修改

1. `agent_runtime/tools/base.py`
   - 增加 `workspace_root` 字段或等效的根目录属性。
   - 改造 `resolve_path()` 的解析和边界校验。
   - 让 `set_working_directory()` 继续使用统一校验。
2. `agent_runtime/runtime/engine.py`
   - 创建 `ToolRuntimeContext` 时显式传入配置级工作区根目录。
   - 校验会话元数据中的当前目录不能超出根目录。
3. 新增或扩展 `tests/` 中的路径安全测试。

### 需要审计但不一定在本需求内修改

`agent_runtime/tools/legacy_adapter.py` 和 `tools/` 下的旧工具有自己的 `cwd`、`allowed_directories` 和路径校验逻辑。它们不一定经过 `ToolRuntimeContext.resolve_path()`，因此本次修改不能自动保证所有旧工具都受同一边界保护。

建议在本需求完成后单独审计以下能力：`read`、`write`、`edit`、`glob`、`grep`、`bash`、`PowerShell` 以及通过旧工具适配器执行的路径操作。旧工具的允许目录应至少包含同一个 `workspace_root`，而不是直接信任可变的会话当前目录。

## 7. 测试需求

建议新增 `tests/test_tool_runtime_context_paths.py`，至少覆盖以下场景：

| 编号 | 场景 | 预期结果 |
| --- | --- | --- |
| T01 | `resolve_path("src/main.py")` | 返回工作区内的规范化路径 |
| T02 | 传入工作区内的绝对路径 | 返回该路径，不报错 |
| T03 | `resolve_path(".")` | 返回工作区根目录或当前工作目录对应的规范化路径 |
| T04 | `resolve_path("..\\outside.txt")` / `../outside.txt` | 抛出路径越界异常 |
| T05 | 传入工作区外的绝对路径 | 抛出路径越界异常 |
| T06 | 工作区内符号链接指向外部目录 | 抛出路径越界异常 |
| T07 | `set_working_directory("child")` | 切换成功，会话元数据同步更新 |
| T08 | `set_working_directory("..")` 导致越过根目录 | 抛出异常，原目录和会话元数据保持不变 |
| T09 | 会话元数据被改为工作区外路径 | 工具执行前拒绝 |
| T10 | 外部路径不存在 | 仍先报路径越界，而不是报“不存在” |
| T11 | Windows 盘符、分隔符和大小写场景 | 不因路径格式差异绕过边界 |
| T12 | 正常 `read_file` 和 `glob_search` | 工作区内行为保持不变 |

符号链接测试在 Windows 上可能需要额外权限；测试应在无法创建符号链接的环境中显式跳过并记录原因，不得删除该安全用例。

## 8. 验收标准

满足以下条件后可认为需求完成：

1. `resolve_path()` 对相对路径、绝对路径、`..` 和符号链接统一执行规范化及边界校验。
2. 任意成功返回的路径都满足 `resolved == workspace_root` 或 `resolved.is_relative_to(workspace_root)`。
3. 工作区外路径不会触发文件读取、目录遍历、文件快照或后续旧工具调用。
4. 会话当前目录可以在工作区内切换，但不能改变工作区根目录或越界。
5. 路径越界会被转换为可识别的工具错误，不导致运行时崩溃。
6. T01-T12 测试全部通过，且现有测试全部通过。
7. 对旧工具适配层的边界行为有明确审计结论；若发现其存在绕过路径，需另行提交修复或在发布说明中标注未覆盖范围。

## 9. 推荐实施顺序

1. 在 `ToolRuntimeContext` 中引入并规范化 `workspace_root`。
2. 改造 `resolve_path()`，采用 `resolve(strict=False)` 加 `is_relative_to()` 校验。
3. 更新 `set_working_directory()` 和运行时引擎的上下文构造。
4. 增加单元测试和符号链接测试。
5. 运行完整测试集，重点验证 `read_file`、`glob_search` 和会话目录切换。
6. 单独审计旧工具适配层的路径边界，确认本次安全边界没有被旧工具绕过。

## 10. 修改要点总结

不建议只在当前实现中增加“绝对路径必须是相对路径”的判断，因为这会错误地拒绝工作区内的绝对路径，也无法单独解决 `..` 和符号链接问题。

推荐方案是：

> 用配置级、不可变的 `workspace_root` 作为唯一安全边界；用当前 `working_directory` 作为相对路径解析基准；对解析后的真实路径执行 `is_relative_to(workspace_root)` 校验。
