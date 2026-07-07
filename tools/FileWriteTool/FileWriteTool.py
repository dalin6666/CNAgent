from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path
from typing import Any

from .._runtime import ToolUseContext, expand_path
from ..FileEditTool.FileEditTool import (
    _get_file_modification_time,
    _normalize_newlines,
    _read_file_metadata,
)
from ..FileEditTool.constants import FILE_UNEXPECTEDLY_MODIFIED_ERROR
from ..FileEditTool.types import gitDiffSchema, hunkSchema
from ..FileEditTool.utils import _structured_patch
from .prompt import DESCRIPTION, FILE_WRITE_TOOL_NAME, getWriteToolDescription

PATCH_CONTEXT_LINES = 3
_TEAM_MEMORY_MARKERS = (
    "/memory/team/",
    "\\memory\\team\\",
)
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "AWS Access Token",
        re.compile(r"\b(?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z2-7]{16}\b"),
    ),
    (
        "Anthropic API Key",
        re.compile(r"\bsk-ant(?:-api03|-admin01)-[A-Za-z0-9_\-]{20,}"),
    ),
    (
        "OpenAI API Key",
        re.compile(
            r"\b(?:sk-(?:proj|svcacct|admin)-[A-Za-z0-9_-]{20,}|"
            r"sk-[A-Za-z0-9]{20}T3BlbkFJ[A-Za-z0-9]{20})"
        ),
    ),
    (
        "GitHub Token",
        re.compile(r"\b(?:ghp_[0-9A-Za-z]{36}|github_pat_\w{82}|gh[ours]_[0-9A-Za-z]{36})\b"),
    ),
    (
        "Private Key",
        re.compile(r"-----BEGIN[ A-Z0-9_-]{0,100}PRIVATE KEY(?: BLOCK)?-----", re.IGNORECASE),
    ),
)


def _normalize_for_match(value: str) -> str:
    normalized = value.replace("\\", "/")
    return normalized.lower() if os.name == "nt" else normalized


def _match_wildcard_pattern(pattern: str, value: str) -> bool:
    return fnmatch.fnmatchcase(_normalize_for_match(value), _normalize_for_match(pattern))


def _get_permission_context(tool_use_context: ToolUseContext | None) -> dict[str, Any]:
    if tool_use_context is None:
        return {}
    app_state = tool_use_context.getAppState()
    context = getattr(app_state, "tool_permission_context", None)
    if isinstance(context, dict):
        return dict(context)
    config = getattr(app_state, "config", {}) or {}
    fallback = config.get("toolPermissionContext")
    return dict(fallback) if isinstance(fallback, dict) else {}


def _matching_rule_for_edit_input(
    file_path: str,
    permission_context: dict[str, Any] | None,
    *,
    behavior: str,
) -> str | None:
    context = dict(permission_context or {})
    candidate_keys = [
        f"{behavior}_edit_rules",
        f"{behavior}EditRules",
        f"edit_{behavior}_rules",
        f"edit{behavior.title()}Rules",
        f"{behavior}_rules",
        f"{behavior}Rules",
    ]
    for key in candidate_keys:
        rules = context.get(key)
        if not isinstance(rules, list):
            continue
        for rule in rules:
            pattern = str(rule)
            if _match_wildcard_pattern(pattern, file_path):
                return pattern
    return None


def _is_team_memory_path(file_path: str) -> bool:
    normalized = file_path.replace("\\", "/").lower()
    return any(marker.replace("\\", "/") in normalized for marker in _TEAM_MEMORY_MARKERS)


def _check_team_memory_secrets(file_path: str, content: str) -> str | None:
    if not _is_team_memory_path(file_path):
        return None
    matches = [label for label, pattern in _SECRET_PATTERNS if pattern.search(content)]
    if not matches:
        return None
    labels = ", ".join(matches)
    return (
        f"Content contains potential secrets ({labels}) and cannot be written to team memory. "
        "Team memory is shared with all repository collaborators. "
        "Remove the sensitive content and try again."
    )


def _write_full_replacement(
    path: Path,
    content: str,
    *,
    encoding: str,
    bom: bytes,
) -> None:
    path.write_bytes(bom + content.encode(encoding))


class PythonFileWriteTool:
    name = FILE_WRITE_TOOL_NAME
    search_hint = "create or overwrite files"
    max_result_size_chars = 100_000
    strict = True
    input_schema = {
        "file_path": "The absolute path to the file to write",
        "content": "The content to write to the file",
    }
    output_schema = {
        "type": "Whether a new file was created or an existing file was updated",
        "filePath": "The path to the file that was written",
        "content": "The content that was written to the file",
        "structuredPatch": hunkSchema(),
        "originalFile": "The original file content before the write",
        "gitDiff": gitDiffSchema(),
    }

    async def description(self, _input_data: dict[str, Any] | None = None) -> str:
        return DESCRIPTION

    async def prompt(self) -> str:
        return getWriteToolDescription()

    def userFacingName(self, input_data: dict[str, Any] | None = None) -> str:
        file_path = str((input_data or {}).get("file_path", ""))
        if f"{os.sep}plans{os.sep}" in file_path:
            return "Updated plan"
        return "Write"

    def getToolUseSummary(self, input_data: dict[str, Any] | None) -> str | None:
        file_path = str((input_data or {}).get("file_path", "")).strip()
        return file_path or None

    def getActivityDescription(self, input_data: dict[str, Any] | None) -> str:
        summary = self.getToolUseSummary(input_data)
        return f"Writing {summary}" if summary else "Writing file"

    def toAutoClassifierInput(self, input_data: dict[str, Any]) -> str:
        return f"{input_data.get('file_path', '')}: {input_data.get('content', '')}"

    def getPath(self, input_data: dict[str, Any]) -> str:
        return str(input_data.get("file_path", ""))

    def backfillObservableInput(self, input_data: dict[str, Any]) -> None:
        file_path = input_data.get("file_path")
        if isinstance(file_path, str):
            input_data["file_path"] = expand_path(file_path)

    async def preparePermissionMatcher(self, payload: dict[str, Any]):
        file_path = expand_path(str(payload.get("file_path", "")))

        def _matcher(pattern: str) -> bool:
            return _match_wildcard_pattern(pattern, file_path)

        return _matcher

    async def checkPermissions(
        self,
        input_data: dict[str, Any],
        context: ToolUseContext | None = None,
    ) -> dict[str, Any]:
        file_path = expand_path(
            str(input_data.get("file_path", "")),
            context.options.cwd if context is not None else None,
        )
        permission_context = _get_permission_context(context)
        deny_rule = _matching_rule_for_edit_input(
            file_path,
            permission_context,
            behavior="deny",
        )
        if deny_rule is not None:
            return {
                "behavior": "deny",
                "message": "File is in a directory that is denied by your permission settings.",
                "decisionReason": {
                    "type": "rule",
                    "rule": deny_rule,
                    "behavior": "deny",
                },
            }
        return {"behavior": "allow", "updatedInput": input_data}

    async def validateInput(
        self,
        input_data: dict[str, Any],
        toolUseContext: ToolUseContext | None = None,
    ) -> dict[str, Any]:
        context = toolUseContext or ToolUseContext()
        file_path = str(input_data.get("file_path", "")).strip()
        content = str(input_data.get("content", ""))
        if not file_path:
            return {
                "result": False,
                "message": "file_path is required.",
                "errorCode": 1,
            }

        full_file_path = expand_path(file_path, context.options.cwd)

        secret_error = _check_team_memory_secrets(full_file_path, content)
        if secret_error:
            return {
                "result": False,
                "message": secret_error,
                "errorCode": 0,
            }

        permission_context = _get_permission_context(context)
        deny_rule = _matching_rule_for_edit_input(
            full_file_path,
            permission_context,
            behavior="deny",
        )
        if deny_rule is not None:
            return {
                "result": False,
                "message": "File is in a directory that is denied by your permission settings.",
                "errorCode": 1,
            }

        if full_file_path.startswith("\\\\") or full_file_path.startswith("//"):
            return {"result": True}

        target = Path(full_file_path)
        try:
            file_mtime_ms = _get_file_modification_time(target)
        except FileNotFoundError:
            return {"result": True}

        read_timestamp = context.read_file_state.get(full_file_path)
        if not read_timestamp or bool(read_timestamp.get("isPartialView")):
            return {
                "result": False,
                "message": "File has not been read yet. Read it first before writing to it.",
                "errorCode": 2,
            }

        if file_mtime_ms > int(read_timestamp.get("timestamp", 0)):
            return {
                "result": False,
                "message": (
                    "File has been modified since read, either by the user or by a linter. "
                    "Read it again before attempting to write it."
                ),
                "errorCode": 3,
            }

        return {"result": True}

    async def call(
        self,
        *args: Any,
        toolUseContext: ToolUseContext | None = None,
        _canUseTool: Any = None,
        parentMessage: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del _canUseTool, parentMessage
        payload = dict(args[0]) if args and isinstance(args[0], dict) else {}
        payload.update(kwargs)
        context = toolUseContext or ToolUseContext()

        validation = await self.validateInput(payload, context)
        if not validation.get("result"):
            raise ValueError(str(validation.get("message", "Invalid file write request.")))

        file_path = str(payload.get("file_path", ""))
        content = str(payload.get("content", ""))
        full_file_path = expand_path(file_path, context.options.cwd)
        target = Path(full_file_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        try:
            meta = _read_file_metadata(target)
        except FileNotFoundError:
            meta = None

        if meta is not None:
            last_write_time = _get_file_modification_time(target)
            last_read = context.read_file_state.get(full_file_path)
            if not last_read or last_write_time > int(last_read.get("timestamp", 0)):
                is_full_read = (
                    last_read is not None
                    and last_read.get("offset") in (None, 1)
                    and last_read.get("limit") is None
                )
                read_snapshot = last_read.get("content") if last_read is not None else None
                content_unchanged = bool(
                    is_full_read
                    and isinstance(read_snapshot, str)
                    and _normalize_newlines(read_snapshot) == _normalize_newlines(meta.content)
                )
                if not content_unchanged:
                    raise ValueError(FILE_UNEXPECTEDLY_MODIFIED_ERROR)

        encoding = meta.encoding if meta is not None else "utf-8"
        bom = meta.bom if meta is not None else b""
        old_content = meta.content if meta is not None else None

        _write_full_replacement(target, content, encoding=encoding, bom=bom)

        context.read_file_state[full_file_path] = {
            "content": content,
            "timestamp": _get_file_modification_time(target),
            "offset": None,
            "limit": None,
            "isPartialView": False,
        }

        if old_content:
            patch = _structured_patch(
                file_path,
                old_content,
                content,
                context=PATCH_CONTEXT_LINES,
            )
            data = {
                "type": "update",
                "filePath": file_path,
                "content": content,
                "structuredPatch": patch,
                "originalFile": old_content,
            }
            return {"data": data}

        data = {
            "type": "create",
            "filePath": file_path,
            "content": content,
            "structuredPatch": [],
            "originalFile": None,
        }
        return {"data": data}

    def mapToolResultToToolResultBlockParam(
        self,
        output: dict[str, Any],
        tool_use_id: str,
    ) -> dict[str, Any]:
        output_type = str(output.get("type", ""))
        file_path = str(output.get("filePath", ""))
        if output_type == "create":
            content = f"File created successfully at: {file_path}"
        else:
            content = f"The file {file_path} has been updated successfully."
        return {
            "tool_use_id": tool_use_id,
            "type": "tool_result",
            "content": content,
        }


FileWriteTool = PythonFileWriteTool()

__all__ = ["FileWriteTool", "PythonFileWriteTool"]
