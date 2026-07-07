from __future__ import annotations

from typing import NotRequired, TypedDict


class FileEditInput(TypedDict, total=False):
    file_path: str
    old_string: str
    new_string: str
    replace_all: bool


class EditInput(TypedDict, total=False):
    old_string: str
    new_string: str
    replace_all: bool


class FileEdit(TypedDict):
    old_string: str
    new_string: str
    replace_all: bool


class Hunk(TypedDict):
    oldStart: int
    oldLines: int
    newStart: int
    newLines: int
    lines: list[str]


class GitDiff(TypedDict, total=False):
    filename: str
    status: str
    additions: int
    deletions: int
    changes: int
    patch: str
    repository: NotRequired[str | None]


class FileEditOutput(TypedDict, total=False):
    filePath: str
    oldString: str
    newString: str
    originalFile: str
    structuredPatch: list[Hunk]
    userModified: bool
    replaceAll: bool
    gitDiff: NotRequired[GitDiff]


def hunkSchema() -> dict[str, str]:
    return {
        'oldStart': 'starting line in the original file',
        'oldLines': 'number of original lines in the hunk',
        'newStart': 'starting line in the updated file',
        'newLines': 'number of updated lines in the hunk',
        'lines': 'unified diff lines for the hunk',
    }


def gitDiffSchema() -> dict[str, str]:
    return {
        'filename': 'path of the changed file',
        'status': 'modified or added',
        'additions': 'number of added lines',
        'deletions': 'number of deleted lines',
        'changes': 'total changed lines',
        'patch': 'git patch text',
        'repository': 'optional owner/repo slug',
    }


def inputSchema() -> dict[str, str]:
    return {
        'file_path': 'The absolute path to the file to modify',
        'old_string': 'The text to replace',
        'new_string': 'The text to replace it with',
        'replace_all': 'Replace all occurrences of old_string (default false)',
    }


def outputSchema() -> dict[str, str]:
    return {
        'filePath': 'The file path that was edited',
        'oldString': 'The original string that was replaced',
        'newString': 'The new string that replaced it',
        'originalFile': 'The original file contents before editing',
        'structuredPatch': 'Diff hunks showing the changes',
        'userModified': 'Whether the user modified the proposed changes',
        'replaceAll': 'Whether all occurrences were replaced',
        'gitDiff': 'Optional git diff metadata',
    }


__all__ = [
    'EditInput',
    'FileEdit',
    'FileEditInput',
    'FileEditOutput',
    'GitDiff',
    'Hunk',
    'gitDiffSchema',
    'hunkSchema',
    'inputSchema',
    'outputSchema',
]
