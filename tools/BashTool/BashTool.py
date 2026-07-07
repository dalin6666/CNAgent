from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from .._runtime import ToolUseContext, create_id, get_task_output_path
from .bashCommandHelpers import split_command_deprecated, split_command_with_operators
from .bashPermissions import bashToolHasPermission, commandHasAnyCd, matchWildcardPattern, permissionRuleExtractPrefix
from .commandSemantics import interpretCommandResult
from .prompt import getDefaultTimeoutMs, getSimplePrompt
from .readOnlyValidation import checkReadOnlyConstraints
from .sedEditParser import applySedSubstitution, parseSedEditCommand
from .shouldUseSandbox import shouldUseSandbox
from .toolName import BASH_TOOL_NAME
from .utils import buildImageToolResult, isImageOutput, stripEmptyLines


EOL = "\n"
PROGRESS_THRESHOLD_MS = 2000
ASSISTANT_BLOCKING_BUDGET_MS = 15_000

# 搜索类Bash命令
BASH_SEARCH_COMMANDS = {"find", "grep", "rg", "ag", "ack", "locate", "which", "whereis"}
# 读取类
BASH_READ_COMMANDS = {
    "cat",
    "head",
    "tail",
    "less",
    "more",
    "wc",
    "stat",
    "file",
    "strings",
    "jq",
    "awk",
    "cut",
    "sort",
    "uniq",
    "tr",
}
# 列表
BASH_LIST_COMMANDS = {"ls", "tree", "du"}
# 中性
BASH_SEMANTIC_NEUTRAL_COMMANDS = {"echo", "printf", "true", "false", ":"}
# 静默
BASH_SILENT_COMMANDS = {
    "mv",
    "cp",
    "rm",
    "mkdir",
    "rmdir",
    "chmod",
    "chown",
    "chgrp",
    "touch",
    "ln",
    "cd",
    "export",
    "unset",
    "wait",
}
DISALLOWED_AUTO_BACKGROUND_COMMANDS = {"sleep"}


def isSearchOrReadBashCommand(command: str) -> dict[str, bool]:
    try:
        parts = split_command_with_operators(command)
    except Exception:
        return {"isSearch": False, "isRead": False, "isList": False}
    if not parts:
        return {"isSearch": False, "isRead": False, "isList": False}
    has_search = False
    has_read = False
    has_list = False
    has_non_neutral_command = False
    skip_next_as_redirect_target = False
    for part in parts:
        if skip_next_as_redirect_target:
            skip_next_as_redirect_target = False
            continue
        if part in {">", ">>", ">&"}:
            skip_next_as_redirect_target = True
            continue
        if part in {"||", "&&", "|", ";"}:
            continue
        base_command = (part.strip().split() or [""])[0]
        if not base_command or base_command in BASH_SEMANTIC_NEUTRAL_COMMANDS:
            continue
        has_non_neutral_command = True
        is_part_search = base_command in BASH_SEARCH_COMMANDS
        is_part_read = base_command in BASH_READ_COMMANDS
        is_part_list = base_command in BASH_LIST_COMMANDS
        if not (is_part_search or is_part_read or is_part_list):
            return {"isSearch": False, "isRead": False, "isList": False}
        has_search = has_search or is_part_search
        has_read = has_read or is_part_read
        has_list = has_list or is_part_list
    if not has_non_neutral_command:
        return {"isSearch": False, "isRead": False, "isList": False}
    return {"isSearch": has_search, "isRead": has_read, "isList": has_list}


def isSilentBashCommand(command: str) -> bool:
    try:
        parts = split_command_with_operators(command)
    except Exception:
        return False
    if not parts:
        return False
    has_non_fallback_command = False
    last_operator: str | None = None
    skip_next_as_redirect_target = False
    for part in parts:
        if skip_next_as_redirect_target:
            skip_next_as_redirect_target = False
            continue
        if part in {">", ">>", ">&"}:
            skip_next_as_redirect_target = True
            continue
        if part in {"||", "&&", "|", ";"}:
            last_operator = part
            continue
        base_command = (part.strip().split() or [""])[0]
        if not base_command:
            continue
        if last_operator == "||" and base_command in BASH_SEMANTIC_NEUTRAL_COMMANDS:
            continue
        has_non_fallback_command = True
        if base_command not in BASH_SILENT_COMMANDS:
            return False
    return has_non_fallback_command


def detectBlockedSleepPattern(command: str) -> str | None:
    parts = split_command_deprecated(command)
    if not parts:
        return None
    first = parts[0].strip()
    match = __import__("re").match(r"^sleep\s+(\d+)\s*$", first)
    if not match:
        return None
    secs = int(match.group(1))
    if secs < 2:
        return None
    rest = " ".join(parts[1:]).strip()
    return f"sleep {secs} followed by: {rest}" if rest else f"standalone sleep {secs}"

"""
bash,powershell,pwsh都是命令行解释器，
bash用于mac,linux系统，powershell面向windows
"""
# 执行环境检测
@lru_cache(maxsize=1)
def _bash_executable() -> str | None:
    # 在系统路径中查找bash,找到返回路径
    candidate = shutil.which("bash")
    if not candidate:
        return None
    try:
        probe = subprocess.run(
            # -l加载环境变量，-c执行后面命令
            [candidate, "-lc", "printf ok"], 
            capture_output=True,  # 捕获stdout/stderr
            text=True,  # 以str形式返回
            timeout=2,  # 最多执行两次
        )
    except Exception:
        return None
    # 当返回码是0（成功执行）同时输出ok，输出bash路径
    return candidate if probe.returncode == 0 and probe.stdout == "ok" else None


@lru_cache(maxsize=1)
def _powershell_executable() -> str | None:
    return shutil.which("pwsh") or shutil.which("powershell")


def _extract_cwd_marker(stderr: str, marker: str) -> tuple[str, str | None]:
    lines = stderr.splitlines()
    kept: list[str] = []
    cwd: str | None = None
    for line in lines:
        if line.startswith(marker):
            cwd = line[len(marker) :]
        else:
            kept.append(line)
    return ("\n".join(kept).rstrip("\n"), cwd)


def _full_env(env: dict[str, str] | None) -> dict[str, str]:
    merged = os.environ.copy()
    if env:
        merged.update({str(key): str(value) for key, value in env.items()})
    return merged


def _normalize_powershell_fallback_command(command: str) -> str:
    stripped = command.strip()
    if stripped == "pwd":
        # Get-Location是ps获取当前目录命令，path获取路径字符串
        return "(Get-Location).Path"
    return command

# 前台执行命令
def _run_foreground_command(
    command: str,
    *,
    cwd: str,  # command运行目录
    timeout_ms: int, # 超时时间
    env: dict[str, str] | None = None, # 可选环境变量
) -> dict[str, Any]:
    # 获取bash路径
    bash = _bash_executable()
    if bash:
        # 构建一个唯一标记
        marker = f"__CLAUDE_CWD__{uuid.uuid4().hex}__"
        # 执行的命令
        """
        trap'...'exit:在shell退出时执行
        printf "\n<marker>%s\n" "$PWD" >&2：打印当前目录，输出到marker
        拼接command
        无论命令中有无cd,都能拿到最终目录
        """
        wrapped = f"trap 'printf \"\\n{marker}%s\\n\" \"$PWD\" >&2' EXIT; {command}"
        argv: list[str] | str = [bash, "-lc", wrapped]
        shell = False
    else:
        powershell = _powershell_executable()
        if powershell:
            # 构造唯一路径，用于从stderr中提取最终目录
            marker = f"__CLAUDE_CWD__{uuid.uuid4().hex}__"
            # 打印当前目录
            ps_command = _normalize_powershell_fallback_command(command)
            wrapped = (
                "$ErrorActionPreference='Continue'; "
                f"& {{ {ps_command} }}; "
                "$__claude_success = $?; "
                "$__claude_exit = if ($LASTEXITCODE -ne $null) { [int]$LASTEXITCODE } "
                "elseif ($__claude_success) { 0 } else { 1 }; "
                f"[Console]::Error.WriteLine('{marker}' + (Get-Location).Path); "
                "exit $__claude_exit"
            )
            argv = [powershell, "-NoProfile", "-Command", wrapped]
            shell = False
        else:
            marker = ""
            argv = command
            shell = True
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            env=_full_env(env),
            shell=shell,
            capture_output=True,
            text=True,
            timeout=max(timeout_ms / 1000.0, 0.001),
        )
        stderr = completed.stderr
        final_cwd = None
        if marker:
            stderr, final_cwd = _extract_cwd_marker(stderr, marker)
        return {
            "command": command,
            "cwd": cwd,
            "code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": stderr,
            "timedOut": False,
            "interrupted": False,
            "finalCwd": final_cwd,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "cwd": cwd,
            "code": -1,
            "stdout": exc.stdout or "",
            "stderr": (exc.stderr or "").rstrip(),
            "timedOut": True,
            "interrupted": True,
            "finalCwd": None,
        }

# 后台执行命令
def _spawn_background_command(
    command: str,
    *,  # 表示调用时必须使用关键字传参
    cwd: str,
    env: dict[str, str] | None,
    description: str | None,
    toolUseContext: ToolUseContext | None,
) -> str:
    task_id = create_id("bash_")  # 创建唯一当前的任务ID
    output_path = Path(get_task_output_path(task_id)) # 获取输出文件路径
    output_path.parent.mkdir(parents=True, exist_ok=True)  # 如果输出文件的父目录不存在，就创建
    bash = _bash_executable()  # 返回系统bash文件路径
    handle = output_path.open("a", encoding="utf-8") # 追加的形式打开文件，在末尾写入，不存在就创建
    try:
        if bash:
            argv: list[str] | str = [bash, "-lc", command]
            shell = False
        else:
            powershell = _powershell_executable()
            if powershell:
                argv = [powershell, "-NoProfile", "-Command", _normalize_powershell_fallback_command(command)]
                shell = False
            else:
                argv = command
                shell = True
        # 启动一个子进程，Popen是立即启动命令，但不会等命令执行完成
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=_full_env(env),
            shell=shell,
            stdout=handle,  # 将标准输出写入文件中
            stderr=subprocess.STDOUT, # 将标准输出重定向到标准输出，也写入到文件中
            text=True,  # 以文本形式处理输入输出，而不是字节
            start_new_session=True,   # 将子进程放入新的会话
        )
    finally:
        handle.close() # 关闭文件句柄
    # 将这个后台任务记录到app_state中
    if toolUseContext is not None:
        toolUseContext.app_state.tasks[task_id] = {
            "status": "running",
            "description": description or command,
            "command": command,
            "cwd": cwd,
            "pid": process.pid,
            "outputFile": str(output_path),
        }
    return task_id


# _表示内部函数，不希望被外部调用
# 将修改后的文件内容，写回新文件
def _apply_sed_edit(
    simulated_edit: dict[str, Any],  # 模拟编辑的结果
    toolUseContext: ToolUseContext | None,
) -> dict[str, Any]:
    file_path = str(simulated_edit["filePath"])  # 被修改的文件路径
    new_content = str(simulated_edit["newContent"]) # 修改后的新内容
    absolute_path = Path(file_path).expanduser()# 强制转换path对象，~/main.py-/home/main.py
    if not absolute_path.is_absolute():
        base = Path(toolUseContext.options.cwd if toolUseContext else os.getcwd())
        absolute_path = (base / absolute_path).resolve()
    try:
        original = absolute_path.read_text(encoding="utf-8")  # 文件修改前的内容
    except FileNotFoundError:
        return {
            "data": {
                "stdout": "",
                "stderr": f"sed: {file_path}: No such file or directory\nExit code 1",
                "interrupted": False,
            }
        }
    # 确定原文件换行风格，如果是\r\n就是windows,如果是\n就是linux风格
    newline = "\r\n" if "\r\n" in original else "\n"
    normalized_new_content = new_content.replace("\n", newline) if newline == "\r\n" else new_content
    # 覆盖并修改源文件
    absolute_path.write_text(normalized_new_content, encoding="utf-8")
    if toolUseContext is not None:
        toolUseContext.read_file_state[str(absolute_path)] = {
            "content": normalized_new_content,
            "timestamp": absolute_path.stat().st_mtime_ns,
            "offset": None,
            "limit": None,
        }
    return {"data": {"stdout": "", "stderr": "", "interrupted": False}}

"""
如何执行命令(前台、后台)
如何控制权限
如何处理cwd(工作目录)
如何处理输出（stdout、stderr）
如何限制危险行为
"""
class PythonBashTool:
    name = BASH_TOOL_NAME
    search_hint = "execute shell commands"
    max_result_size_chars = 30_000  # 输出最大长度
    strict = True  # 是否严格模式
    # Tool能接收什么
    input_schema = {
        "command": "The command to execute",
        "timeout": "Optional timeout in milliseconds",
        "description": "Optional user-facing description",
        "run_in_background": "Run this command in the background",# 是否后台运行
        "dangerouslyDisableSandbox": "Disable sandboxing when available", # 关闭沙箱
        "_simulatedSedEdit": "Internal precomputed sed edit result",
        "cwd": "Optional working directory override",
        "env": "Optional environment overrides",
    }
    # Tool能输出什么
    output_schema = {
        "stdout": "The standard output of the command",
        "stderr": "The standard error output of the command",
        "interrupted": "Whether the command was interrupted",
        "isImage": "Whether stdout contains a data-uri image",
        "backgroundTaskId": "Task identifier for background execution",
        "returnCodeInterpretation": "Semantic interpretation for a non-error exit code",
        "noOutputExpected": "Whether success usually produces no output",
        "dangerouslyDisableSandbox": "Whether sandboxing was disabled",
    }

    async def description(self, input_data: dict[str, Any] | None = None) -> str:
        if input_data and input_data.get("description"):
            return str(input_data["description"])
        return "Run shell command"

    async def prompt(self) -> str:
        return getSimplePrompt()

    #  判断当前命令是否值得并发执行
    def isConcurrencySafe(self, input_data: dict[str, Any]) -> bool:
        return self.isReadOnly(input_data)

    def isReadOnly(self, input_data: dict[str, Any]) -> bool:
        result = checkReadOnlyConstraints(input_data, commandHasAnyCd(str(input_data.get("command", ""))))
        return result.get("behavior") == "allow"

    def toAutoClassifierInput(self, input_data: dict[str, Any]) -> str:
        return str(input_data.get("command", ""))

    # 根据传入的命令，生成一个权限匹配器
    """
    权限pattern：ls,cat,grep *,python *等
    表示允许ls,cat,grep任何文件，python任何文件
    """
    async def preparePermissionMatcher(self, command: str):
        subcommands = split_command_deprecated(command) # 将命令拆成多个子命令

        # 嵌套函数，输入某个权限判断是否匹配当前command
        # 嵌套函数可以使用外层函数的变量
        # 正割函数判断的是当前pattern是否匹配command中的某一个部分
        def _matcher(pattern: str) -> bool:
            prefix = permissionRuleExtractPrefix(pattern)
            for subcommand in subcommands:
                if prefix is not None:
                    if subcommand == prefix or subcommand.startswith(prefix + " "):
                        return True
                elif matchWildcardPattern(pattern, subcommand):
                    return True
            return False

        return _matcher

    # 判断当前command是否属于搜索或读取类
    def isSearchOrReadCommand(self, input_data: dict[str, Any]) -> dict[str, bool]:
        return isSearchOrReadBashCommand(str(input_data.get("command", "")))

    def userFacingName(self, input_data: dict[str, Any] | None = None) -> str:
        if input_data and input_data.get("command"):
            sed_info = parseSedEditCommand(str(input_data["command"]))
            if sed_info:
                return f"Edit {sed_info['filePath']}"
        if input_data and shouldUseSandbox(input_data):
            return "SandboxedBash"
        return "Bash"

    def getToolUseSummary(self, input_data: dict[str, Any] | None) -> str | None:
        if not input_data or not input_data.get("command"):
            return None
        if input_data.get("description"):
            return str(input_data["description"])
        command = str(input_data["command"])
        return command if len(command) <= 120 else command[:117] + "..."

    def getActivityDescription(self, input_data: dict[str, Any] | None) -> str:
        summary = self.getToolUseSummary(input_data)
        return f"Running {summary}" if summary else "Running command"

    # 检测command中是否包含被禁止的sleep/wait权限，例如sleep,timeout等
    async def validateInput(self, input_data: dict[str, Any]) -> dict[str, Any]:
        if not input_data.get("run_in_background"):
            sleep_pattern = detectBlockedSleepPattern(str(input_data.get("command", "")))
            if sleep_pattern is not None:
                return {
                    "result": False,
                    "message": (
                        f"Blocked: {sleep_pattern}. Run long waits in the background with "
                        "run_in_background: true or keep deliberate delays under 2 seconds."
                    ),
                    "errorCode": 10,
                }
        return {"result": True}

    async def checkPermissions(
        self,
        input_data: dict[str, Any],
        context: ToolUseContext | None = None,
    ) -> dict[str, Any]:
        return await bashToolHasPermission(input_data, context)

    def extractSearchText(self, output: dict[str, Any]) -> str:
        stdout = str(output.get("stdout", ""))
        stderr = str(output.get("stderr", ""))
        return f"{stdout}\n{stderr}" if stderr else stdout

    def mapToolResultToToolResultBlockParam(
        self,
        output: dict[str, Any],
        toolUseID: str,
    ) -> dict[str, Any]:
        if output.get("structuredContent"):
            return {
                "tool_use_id": toolUseID,
                "type": "tool_result",
                "content": output["structuredContent"],
            }
        if output.get("isImage"):
            block = buildImageToolResult(str(output.get("stdout", "")), toolUseID)
            if block is not None:
                return block
        content_parts = []
        stdout = str(output.get("stdout", "")).lstrip("\n").rstrip()
        stderr = str(output.get("stderr", "")).rstrip()
        if stdout:
            content_parts.append(stdout)
        if stderr:
            content_parts.append(stderr)
        if output.get("interrupted"):
            content_parts.append("<error>Command was aborted before completion</error>")
        if output.get("backgroundTaskId"):
            content_parts.append(
                f"Command running in background with ID: {output['backgroundTaskId']}. "
                f"Output is being written to: {get_task_output_path(str(output['backgroundTaskId']))}"
            )
        return {
            "tool_use_id": toolUseID,
            "type": "tool_result",
            "content": "\n".join(part for part in content_parts if part),
            "is_error": bool(output.get("interrupted")),
        }

    async def call(
        self,
        *args: Any,
        toolUseContext: ToolUseContext | None = None,  # 记录工作目录，应用状态，消息列表，任务状态
        _canUseTool: Any = None,
        parentMessage: Any = None,
        onProgress: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del _canUseTool, parentMessage, onProgress # 当前函数不会使用，只是为了兼容接口，避免代码检查工具报错
        if args and isinstance(args[0], dict):
            payload = dict(args[0])
            payload.update(kwargs)
        else:
            payload = dict(kwargs)
        if payload.get("_simulatedSedEdit"):
            return _apply_sed_edit(dict(payload["_simulatedSedEdit"]), toolUseContext)
        command = str(payload["command"])
        timeout_ms = int(payload.get("timeout") or getDefaultTimeoutMs())
        description = payload.get("description")
        env = payload.get("env")
        requested_cwd = payload.get("cwd")
        base_cwd = toolUseContext.options.cwd if toolUseContext else os.getcwd()
        effective_cwd = str(Path(requested_cwd).expanduser().resolve()) if requested_cwd else base_cwd
        if payload.get("run_in_background"):
            task_id = _spawn_background_command(
                command,
                cwd=effective_cwd,
                env=env if isinstance(env, dict) else None,
                description=str(description) if description else None,
                toolUseContext=toolUseContext,
            )
            return {
                "data": {
                    "stdout": "",
                    "stderr": "",
                    "interrupted": False,
                    "backgroundTaskId": task_id,
                    "dangerouslyDisableSandbox": bool(payload.get("dangerouslyDisableSandbox")),
                }
            }
        result = _run_foreground_command(
            command,
            cwd=effective_cwd,
            timeout_ms=timeout_ms,
            env=env if isinstance(env, dict) else None,
        )
        if toolUseContext is not None and result.get("finalCwd"):
            toolUseContext.options.cwd = str(result["finalCwd"])
        stdout = stripEmptyLines(str(result.get("stdout", "")))
        stderr = str(result.get("stderr", "")).strip()
        if result.get("timedOut"):
            timeout_suffix = f"Command timed out after {timeout_ms}ms"
            stderr = f"{stderr}{EOL if stderr else ''}{timeout_suffix}"
        interpretation = interpretCommandResult(command, int(result.get("code", 0)), stdout, stderr)
        if interpretation.get("isError") and result.get("code") not in {0, None}:
            stderr = f"{stderr}{EOL if stderr else ''}Exit code {result['code']}"
        data = {
            "stdout": stdout,
            "stderr": stderr,
            "interrupted": bool(result.get("interrupted")),
            "isImage": isImageOutput(stdout),
            "returnCodeInterpretation": interpretation.get("message"),
            "noOutputExpected": isSilentBashCommand(command),
            "backgroundTaskId": None,
            "backgroundedByUser": False,
            "assistantAutoBackgrounded": False,
            "dangerouslyDisableSandbox": bool(payload.get("dangerouslyDisableSandbox")),
            "sandboxEnabled": shouldUseSandbox(payload),
        }
        return {"data": data}

    def isResultTruncated(self, output: dict[str, Any]) -> bool:
        return len(str(output.get("stdout", ""))) > self.max_result_size_chars or len(
            str(output.get("stderr", ""))
        ) > self.max_result_size_chars


BashTool = PythonBashTool()

__all__ = [
    "ASSISTANT_BLOCKING_BUDGET_MS",
    "BashTool",
    "PROGRESS_THRESHOLD_MS",
    "PythonBashTool",
    "detectBlockedSleepPattern",
    "isSearchOrReadBashCommand",
]
