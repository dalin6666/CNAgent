from __future__ import annotations

from ..BashTool.toolName import BASH_TOOL_NAME

FILE_READ_TOOL_NAME = 'Read'

FILE_UNCHANGED_STUB = (
    'File unchanged since last read. The content from the earlier Read '
    'tool_result in this conversation is still current - refer to that '
    'instead of re-reading.'
)

MAX_LINES_TO_READ = 2000

DESCRIPTION = 'Read a file from the local filesystem.'

LINE_FORMAT_INSTRUCTION = (
    '- Results are returned using cat -n format, with line numbers starting at 1'
)

OFFSET_INSTRUCTION_DEFAULT = (
    "- You can optionally specify a line offset and limit (especially handy "
    "for long files), but it's recommended to read the whole file by not "
    'providing these parameters'
)

OFFSET_INSTRUCTION_TARGETED = (
    '- When you already know which part of the file you need, only read that '
    'part. This can be important for larger files.'
)


def renderPromptTemplate(
    lineFormat: str,
    maxSizeInstruction: str,
    offsetInstruction: str,
) -> str:
    return (
        'Reads a file from the local filesystem. You can access any file '
        'directly by using this tool.\n'
        'Assume this tool is able to read all files on the machine. If the '
        'User provides a path to a file assume that path is valid. It is okay '
        'to read a file that does not exist; an error will be returned.\n\n'
        'Usage:\n'
        '- The file_path parameter must be an absolute path, not a relative path\n'
        f'- By default, it reads up to {MAX_LINES_TO_READ} lines starting from '
        f'the beginning of the file{maxSizeInstruction}\n'
        f'{offsetInstruction}\n'
        f'{lineFormat}\n'
        '- This tool allows Claude Code to read images (eg PNG, JPG, etc). '
        'When reading an image file the contents are presented visually as '
        'Claude Code is a multimodal LLM.\n'
        '- This tool can read PDF files (.pdf). For large PDFs (more than 10 '
        'pages), you should provide the pages parameter to read specific page '
        'ranges (for example pages: "1-5"). Some Python environments require '
        'additional PDF utilities for page extraction.\n'
        '- This tool can read Jupyter notebooks (.ipynb files) and returns '
        'all cells with their outputs, combining code, text, and visualizations.\n'
        f'- This tool can only read files, not directories. To read a '
        f'directory, use an ls command via the {BASH_TOOL_NAME} tool.\n'
        '- You will regularly be asked to read screenshots. If the user '
        'provides a path to a screenshot, always use this tool to view the '
        'file at the path. This tool will work with temporary file paths.\n'
        '- If you read a file that exists but has empty contents you will '
        'receive a system reminder warning in place of file contents.'
    )


__all__ = [
    'DESCRIPTION',
    'FILE_READ_TOOL_NAME',
    'FILE_UNCHANGED_STUB',
    'LINE_FORMAT_INSTRUCTION',
    'MAX_LINES_TO_READ',
    'OFFSET_INSTRUCTION_DEFAULT',
    'OFFSET_INSTRUCTION_TARGETED',
    'renderPromptTemplate',
]
