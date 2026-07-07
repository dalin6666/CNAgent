from __future__ import annotations

FILE_EDIT_TOOL_NAME = 'Edit'

CLAUDE_FOLDER_PERMISSION_PATTERN = '/.claude/**'
GLOBAL_CLAUDE_FOLDER_PERMISSION_PATTERN = '~/.claude/**'

FILE_UNEXPECTEDLY_MODIFIED_ERROR = (
    'File has been unexpectedly modified. Read it again before attempting to write it.'
)

__all__ = [
    'CLAUDE_FOLDER_PERMISSION_PATTERN',
    'FILE_EDIT_TOOL_NAME',
    'FILE_UNEXPECTEDLY_MODIFIED_ERROR',
    'GLOBAL_CLAUDE_FOLDER_PERMISSION_PATTERN',
]
