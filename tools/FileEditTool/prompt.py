from __future__ import annotations

from ..FileReadTool.prompt import FILE_READ_TOOL_NAME


def getEditToolDescription() -> str:
    return (
        'Performs exact string replacements in files.\n\n'
        'Usage:\n'
        f'- You must use your `{FILE_READ_TOOL_NAME}` tool at least once in the conversation before editing. '
        'This tool will error if you attempt an edit without reading the file.\n'
        '- When editing text from Read tool output, preserve the exact indentation after the line number prefix. '
        'Never include any part of the line number prefix in old_string or new_string.\n'
        '- ALWAYS prefer editing existing files in the codebase. NEVER write new files unless explicitly required.\n'
        '- Only use emojis if the user explicitly requests it.\n'
        '- The edit will FAIL if old_string is not unique in the file. Provide more context or use replace_all '
        'when you intend to replace every occurrence.\n'
        '- Use replace_all for replacing and renaming strings across a file.'
    )


__all__ = ['getEditToolDescription']
