from __future__ import annotations

import codecs
import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .._runtime import ToolUseContext, expand_path
from .constants import FILE_EDIT_TOOL_NAME, FILE_UNEXPECTEDLY_MODIFIED_ERROR
from .prompt import getEditToolDescription
from .types import FileEditInput, FileEditOutput, inputSchema, outputSchema
from .utils import (
    areFileEditsInputsEquivalent,
    findActualString,
    getPatchForEdit,
    preserveQuoteStyle,
)

FILE_NOT_FOUND_CWD_NOTE = 'Note: your current working directory is'
NOTEBOOK_EDIT_TOOL_NAME = 'NotebookEdit'
MAX_EDIT_FILE_SIZE = 1024 * 1024 * 1024


@dataclass(frozen=True)
class _FileReadMetadata:
    content: str
    encoding: str
    line_endings: str
    bom: bytes


@dataclass(frozen=True)
class _ReadState:
    content: str
    file_exists: bool
    encoding: str
    line_endings: str
    bom: bytes


class PythonFileEditTool:
    name = FILE_EDIT_TOOL_NAME
    search_hint = 'modify file contents in place'
    max_result_size_chars = 100_000
    strict = True
    input_schema = inputSchema()
    output_schema = outputSchema()

    async def description(self, _input_data: dict[str, Any] | None = None) -> str:
        return 'A tool for editing files'

    async def prompt(self) -> str:
        return getEditToolDescription()

    def userFacingName(self, input_data: dict[str, Any] | None = None) -> str:
        if input_data and input_data.get('old_string') == '':
            return 'Create'
        return 'Update'

    def getToolUseSummary(self, input_data: dict[str, Any] | None) -> str | None:
        if not input_data or not input_data.get('file_path'):
            return None
        return str(input_data['file_path'])

    def getActivityDescription(self, input_data: dict[str, Any] | None) -> str:
        summary = self.getToolUseSummary(input_data)
        return f'Editing {summary}' if summary else 'Editing file'

    def toAutoClassifierInput(self, input_data: dict[str, Any]) -> str:
        return f"{input_data.get('file_path', '')}: {input_data.get('new_string', '')}"

    def getPath(self, input_data: dict[str, Any]) -> str:
        return str(input_data.get('file_path', ''))

    def backfillObservableInput(self, input_data: dict[str, Any]) -> None:
        if isinstance(input_data.get('file_path'), str):
            input_data['file_path'] = expand_path(input_data['file_path'])

    async def preparePermissionMatcher(self, payload: dict[str, Any]):
        file_path = str(payload.get('file_path', ''))

        def _matcher(pattern: str) -> bool:
            normalized_pattern = pattern.replace('/', '\\')
            normalized_file_path = file_path.replace('/', '\\')
            return fnmatch.fnmatch(normalized_file_path, normalized_pattern)

        return _matcher

    async def checkPermissions(
        self,
        input_data: dict[str, Any],
        _context: ToolUseContext | None = None,
    ) -> dict[str, Any]:
        return {'behavior': 'allow', 'updatedInput': input_data}

    async def validateInput(
        self,
        input_data: FileEditInput | dict[str, Any],
        toolUseContext: ToolUseContext | None = None,
    ) -> dict[str, Any]:
        file_path = str(input_data.get('file_path', ''))
        old_string = str(input_data.get('old_string', ''))
        new_string = str(input_data.get('new_string', ''))
        replace_all = bool(input_data.get('replace_all', False))
        context = toolUseContext or ToolUseContext()
        full_file_path = expand_path(file_path, context.options.cwd)

        if old_string == new_string:
            return {
                'result': False,
                'behavior': 'ask',
                'message': 'No changes to make: old_string and new_string are exactly the same.',
                'errorCode': 1,
            }

        if full_file_path.startswith('\\\\') or full_file_path.startswith('//'):
            return {'result': True}

        target = Path(full_file_path)
        try:
            if target.exists() and target.stat().st_size > MAX_EDIT_FILE_SIZE:
                return {
                    'result': False,
                    'behavior': 'ask',
                    'message': (
                        f'File is too large to edit ({_format_file_size(target.stat().st_size)}). '
                        f'Maximum editable file size is {_format_file_size(MAX_EDIT_FILE_SIZE)}.'
                    ),
                    'errorCode': 10,
                }
        except OSError:
            pass

        file_content: str | None
        try:
            file_content = _read_file_metadata(target).content
        except FileNotFoundError:
            file_content = None

        if file_content is None:
            if old_string == '':
                return {'result': True}
            similar_filename = _find_similar_file(target)
            cwd_suggestion = _suggest_path_under_cwd(target, context.options.cwd)
            message = f'File does not exist. {FILE_NOT_FOUND_CWD_NOTE} {context.options.cwd}.'
            if cwd_suggestion:
                message += f' Did you mean {cwd_suggestion}?'
            elif similar_filename:
                message += f' Did you mean {similar_filename}?'
            return {
                'result': False,
                'behavior': 'ask',
                'message': message,
                'errorCode': 4,
            }

        if old_string == '':
            if file_content.strip() != '':
                return {
                    'result': False,
                    'behavior': 'ask',
                    'message': 'Cannot create new file - file already exists.',
                    'errorCode': 3,
                }
            return {'result': True}

        if full_file_path.endswith('.ipynb'):
            return {
                'result': False,
                'behavior': 'ask',
                'message': (
                    f'File is a Jupyter Notebook. Use the {NOTEBOOK_EDIT_TOOL_NAME} '
                    'tool to edit this file.'
                ),
                'errorCode': 5,
            }

        read_timestamp = context.read_file_state.get(full_file_path)
        if not read_timestamp or bool(read_timestamp.get('isPartialView')):
            return {
                'result': False,
                'behavior': 'ask',
                'message': 'File has not been read yet. Read it first before writing to it.',
                'meta': {'isFilePathAbsolute': str(Path(file_path).is_absolute())},
                'errorCode': 6,
            }

        last_write_time = _get_file_modification_time(target)
        read_time = int(read_timestamp.get('timestamp', 0))
        if last_write_time > read_time:
            is_full_read = (
                read_timestamp.get('offset') in (None, 1)
                and read_timestamp.get('limit') is None
            )
            read_snapshot = read_timestamp.get('content')
            content_unchanged = (
                is_full_read
                and isinstance(read_snapshot, str)
                and _normalize_newlines(read_snapshot) == _normalize_newlines(file_content)
            )
            if not content_unchanged:
                return {
                    'result': False,
                    'behavior': 'ask',
                    'message': (
                        'File has been modified since read, either by the user or by a '
                        'formatter. Read it again before attempting to write it.'
                    ),
                    'errorCode': 7,
                }

        actual_old_string = findActualString(file_content, old_string)
        if not actual_old_string:
            return {
                'result': False,
                'behavior': 'ask',
                'message': f'String to replace not found in file.\nString: {old_string}',
                'meta': {'isFilePathAbsolute': str(Path(file_path).is_absolute())},
                'errorCode': 8,
            }

        matches = file_content.count(actual_old_string)
        if matches > 1 and not replace_all:
            return {
                'result': False,
                'behavior': 'ask',
                'message': (
                    f'Found {matches} matches of the string to replace, but replace_all is false. '
                    'To replace all occurrences, set replace_all to true. To replace only one '
                    'occurrence, provide more surrounding context.\n'
                    f'String: {old_string}'
                ),
                'meta': {
                    'isFilePathAbsolute': str(Path(file_path).is_absolute()),
                    'actualOldString': actual_old_string,
                },
                'errorCode': 9,
            }

        return {'result': True, 'meta': {'actualOldString': actual_old_string}}

    def inputsEquivalent(self, input1: dict[str, Any], input2: dict[str, Any]) -> bool:
        return areFileEditsInputsEquivalent(
            {
                'file_path': input1.get('file_path', ''),
                'edits': [
                    {
                        'old_string': input1.get('old_string', ''),
                        'new_string': input1.get('new_string', ''),
                        'replace_all': bool(input1.get('replace_all', False)),
                    }
                ],
            },
            {
                'file_path': input2.get('file_path', ''),
                'edits': [
                    {
                        'old_string': input2.get('old_string', ''),
                        'new_string': input2.get('new_string', ''),
                        'replace_all': bool(input2.get('replace_all', False)),
                    }
                ],
            },
        )

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
        if not validation.get('result'):
            raise ValueError(str(validation.get('message', 'Invalid file edit request.')))

        file_path = str(payload.get('file_path', ''))
        old_string = str(payload.get('old_string', ''))
        new_string = str(payload.get('new_string', ''))
        replace_all = bool(payload.get('replace_all', False))

        absolute_file_path = expand_path(file_path, context.options.cwd)
        target = Path(absolute_file_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        file_state = _read_file_for_edit(target)
        original_file_contents = file_state.content

        if file_state.file_exists:
            last_read = context.read_file_state.get(absolute_file_path)
            last_write_time = _get_file_modification_time(target)
            if not last_read or last_write_time > int(last_read.get('timestamp', 0)):
                is_full_read = (
                    last_read is not None
                    and last_read.get('offset') in (None, 1)
                    and last_read.get('limit') is None
                )
                read_snapshot = last_read.get('content') if last_read is not None else None
                content_unchanged = bool(
                    is_full_read
                    and isinstance(read_snapshot, str)
                    and _normalize_newlines(read_snapshot)
                    == _normalize_newlines(original_file_contents)
                )
                if not content_unchanged:
                    raise ValueError(FILE_UNEXPECTEDLY_MODIFIED_ERROR)

        actual_old_string = findActualString(original_file_contents, old_string) or old_string
        actual_new_string = preserveQuoteStyle(old_string, actual_old_string, new_string)
        patch_result = getPatchForEdit(
            filePath=absolute_file_path,
            fileContents=original_file_contents,
            oldString=actual_old_string,
            newString=actual_new_string,
            replaceAll=replace_all,
        )
        patch = patch_result['patch']
        updated_file = str(patch_result['updatedFile'])
        _write_text_content(
            target,
            updated_file,
            encoding=file_state.encoding,
            line_endings=file_state.line_endings,
            bom=file_state.bom,
        )

        context.read_file_state[absolute_file_path] = {
            'content': updated_file,
            'timestamp': _get_file_modification_time(target),
            'offset': None,
            'limit': None,
            'isPartialView': False,
        }

        data: FileEditOutput = {
            'filePath': file_path,
            'oldString': actual_old_string,
            'newString': new_string,
            'originalFile': original_file_contents,
            'structuredPatch': patch,
            'userModified': bool(payload.get('userModified', False)),
            'replaceAll': replace_all,
        }
        return {'data': data}

    def mapToolResultToToolResultBlockParam(
        self,
        output: FileEditOutput | dict[str, Any],
        tool_use_id: str,
    ) -> dict[str, Any]:
        file_path = str(output.get('filePath', ''))
        user_modified = bool(output.get('userModified', False))
        replace_all = bool(output.get('replaceAll', False))
        modified_note = (
            '. The user modified your proposed changes before accepting them. '
            if user_modified
            else ''
        )
        if replace_all:
            content = (
                f'The file {file_path} has been updated{modified_note}. '
                'All occurrences were successfully replaced.'
            )
        else:
            content = f'The file {file_path} has been updated successfully{modified_note}.'
        return {'tool_use_id': tool_use_id, 'type': 'tool_result', 'content': content}


def _read_file_for_edit(path: Path) -> _ReadState:
    try:
        metadata = _read_file_metadata(path)
        return _ReadState(
            content=metadata.content,
            file_exists=True,
            encoding=metadata.encoding,
            line_endings=metadata.line_endings,
            bom=metadata.bom,
        )
    except FileNotFoundError:
        return _ReadState(
            content='',
            file_exists=False,
            encoding='utf-8',
            line_endings='LF',
            bom=b'',
        )


def _read_file_metadata(path: Path) -> _FileReadMetadata:
    raw = path.read_bytes()
    encoding = 'utf-8'
    bom = b''
    body = raw
    if raw.startswith(codecs.BOM_UTF8):
        bom = codecs.BOM_UTF8
        body = raw[len(codecs.BOM_UTF8) :]
    elif raw.startswith(codecs.BOM_UTF16_LE):
        encoding = 'utf-16le'
        bom = codecs.BOM_UTF16_LE
        body = raw[len(codecs.BOM_UTF16_LE) :]
    elif raw.startswith(codecs.BOM_UTF16_BE):
        encoding = 'utf-16be'
        bom = codecs.BOM_UTF16_BE
        body = raw[len(codecs.BOM_UTF16_BE) :]
    content = body.decode(encoding, errors='replace')
    line_endings = _detect_line_endings(content)
    return _FileReadMetadata(
        content=content,
        encoding=encoding,
        line_endings=line_endings,
        bom=bom,
    )


def _write_text_content(
    path: Path,
    content: str,
    *,
    encoding: str,
    line_endings: str,
    bom: bytes,
) -> None:
    normalized = content.replace('\r\n', '\n').replace('\r', '\n')
    if line_endings == 'CRLF':
        normalized = normalized.replace('\n', '\r\n')
    elif line_endings == 'CR':
        normalized = normalized.replace('\n', '\r')
    path.write_bytes(bom + normalized.encode(encoding))


def _detect_line_endings(content: str) -> str:
    if '\r\n' in content:
        return 'CRLF'
    if '\r' in content:
        return 'CR'
    return 'LF'


def _get_file_modification_time(path: Path) -> int:
    return int(path.stat().st_mtime_ns // 1_000_000)


def _find_similar_file(path: Path) -> str | None:
    try:
        siblings = list(path.parent.iterdir())
    except OSError:
        return None
    for sibling in siblings:
        if sibling == path:
            continue
        if sibling.stem == path.stem:
            return sibling.name
    return None


def _suggest_path_under_cwd(path: Path, cwd: str) -> str | None:
    cwd_path = Path(cwd).resolve()
    cwd_parent = cwd_path.parent
    try:
        resolved_path = path.parent.resolve() / path.name
    except OSError:
        resolved_path = path
    try:
        resolved_path.relative_to(cwd_parent)
    except ValueError:
        return None
    try:
        resolved_path.relative_to(cwd_path)
        return None
    except ValueError:
        pass
    try:
        relative_to_parent = resolved_path.relative_to(cwd_parent)
    except ValueError:
        return None
    corrected_path = cwd_path / relative_to_parent
    return str(corrected_path) if corrected_path.exists() else None


def _format_file_size(size: int) -> str:
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == 'B':
                return f'{int(value)} {unit}'
            return f'{value:.1f} {unit}'
        value /= 1024
    return f'{size} B'


def _normalize_newlines(content: str) -> str:
    return content.replace('\r\n', '\n').replace('\r', '\n')


FileEditTool = PythonFileEditTool()

__all__ = ['FileEditTool', 'PythonFileEditTool']
