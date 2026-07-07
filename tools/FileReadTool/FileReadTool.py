from __future__ import annotations

import base64
import fnmatch
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from ..BashTool.toolName import BASH_TOOL_NAME
from .._runtime import STATE_ROOT, TASK_OUTPUT_ROOT, ToolUseContext, expand_path
from .imageProcessor import (
    compress_image_with_token_limit,
    detect_image_media_type,
    maybe_resize_and_downsample_image_bytes,
)
from .limits import getDefaultFileReadingLimits
from .prompt import (
    DESCRIPTION,
    FILE_READ_TOOL_NAME,
    FILE_UNCHANGED_STUB,
    LINE_FORMAT_INSTRUCTION,
    OFFSET_INSTRUCTION_DEFAULT,
    OFFSET_INSTRUCTION_TARGETED,
    renderPromptTemplate,
)


FILE_NOT_FOUND_CWD_NOTE = 'Note: your current working directory is'
PLAN_ROOT = STATE_ROOT / 'plans'
PDF_AT_MENTION_INLINE_THRESHOLD = 10
PDF_MAX_PAGES_PER_READ = 20
MAX_INLINE_PDF_BYTES = 20 * 1024 * 1024

CYBER_RISK_MITIGATION_REMINDER = (
    '\n\n<system-reminder>\n'
    'Whenever you read a file, you should consider whether it would be '
    'considered malware. You can and should provide analysis of malware and '
    'what it is doing. But you must refuse to improve or augment the code. '
    'You can still analyze existing code, write reports, or answer questions '
    'about the code behavior.\n'
    '</system-reminder>\n'
)

BLOCKED_DEVICE_PATHS = {
    '/dev/zero',
    '/dev/random',
    '/dev/urandom',
    '/dev/full',
    '/dev/stdin',
    '/dev/tty',
    '/dev/console',
    '/dev/stdout',
    '/dev/stderr',
    '/dev/fd/0',
    '/dev/fd/1',
    '/dev/fd/2',
}

IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'}
PDF_EXTENSIONS = {'pdf'}
BINARY_EXTENSIONS = {
    '.7z',
    '.a',
    '.bin',
    '.class',
    '.dll',
    '.dylib',
    '.ear',
    '.exe',
    '.gz',
    '.ico',
    '.jar',
    '.lib',
    '.o',
    '.obj',
    '.pdb',
    '.pyc',
    '.so',
    '.tar',
    '.war',
    '.zip',
}

THIN_SPACE = chr(8239)

_FILE_READ_LISTENERS: list[Callable[[str, str], None]] = []


class MaxFileReadTokenExceededError(RuntimeError):
    def __init__(self, tokenCount: int, maxTokens: int) -> None:
        super().__init__(
            'File content '
            f'({tokenCount} tokens) exceeds maximum allowed tokens ({maxTokens}). '
            'Use offset and limit parameters to read specific portions of the '
            'file, or search for specific content instead of reading the whole '
            'file.'
        )
        self.tokenCount = tokenCount
        self.maxTokens = maxTokens


def registerFileReadListener(listener: Callable[[str, str], None]):
    _FILE_READ_LISTENERS.append(listener)

    def _unsubscribe() -> None:
        if listener in _FILE_READ_LISTENERS:
            _FILE_READ_LISTENERS.remove(listener)

    return _unsubscribe


def isBlockedDevicePath(filePath: str) -> bool:
    if filePath in BLOCKED_DEVICE_PATHS:
        return True
    if filePath.startswith('/proc/') and filePath.endswith(('/fd/0', '/fd/1', '/fd/2')):
        return True
    return False


def getAlternateScreenshotPath(filePath: str) -> str | None:
    filename = os.path.basename(filePath)
    match = re.match(r'^(.+)([ \u202f])(AM|PM)(\.png)$', filename)
    if not match:
        return None
    current_space = match.group(2)
    alternate_space = THIN_SPACE if current_space == ' ' else ' '
    return filePath.replace(
        f'{current_space}{match.group(3)}{match.group(4)}',
        f'{alternate_space}{match.group(3)}{match.group(4)}',
    )


def _normalize_for_match(value: str) -> str:
    normalized = value.replace('\\', '/')
    return normalized.lower() if os.name == 'nt' else normalized


def _match_wildcard_pattern(pattern: str, value: str) -> bool:
    return fnmatch.fnmatchcase(_normalize_for_match(value), _normalize_for_match(pattern))


def _get_permission_context(toolUseContext: ToolUseContext | None) -> dict[str, Any]:
    if toolUseContext is None:
        return {}
    app_state = toolUseContext.getAppState()
    if hasattr(app_state, 'tool_permission_context'):
        context = getattr(app_state, 'tool_permission_context')
        if isinstance(context, dict):
            return dict(context)
    config = getattr(app_state, 'config', {}) or {}
    fallback = config.get('toolPermissionContext')
    return dict(fallback) if isinstance(fallback, dict) else {}


def _matching_rule_for_input(
    file_path: str,
    permission_context: dict[str, Any] | None,
    *,
    behavior: str,
) -> str | None:
    context = dict(permission_context or {})
    candidate_keys = [
        f'{behavior}_read_rules',
        f'{behavior}ReadRules',
        f'{behavior}_rules',
        f'{behavior}Rules',
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


def _parse_pdf_page_range(value: str) -> tuple[int, int] | None:
    match = re.fullmatch(r'\s*(\d+)\s*(?:-\s*(\d+)\s*)?', value)
    if not match:
        return None
    first = int(match.group(1))
    last = int(match.group(2) or match.group(1))
    if first < 1 or last < first:
        return None
    return first, last


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


def _display_path(file_path: str) -> str:
    try:
        cwd = Path.cwd().resolve()
        target = Path(file_path).resolve()
        return str(target.relative_to(cwd))
    except (OSError, ValueError):
        return file_path


def _get_agent_output_task_id(file_path: str) -> str | None:
    prefix = f'{TASK_OUTPUT_ROOT}{os.sep}'
    suffix = '.txt'
    if file_path.startswith(prefix) and file_path.endswith(suffix):
        task_id = file_path[len(prefix) : -len(suffix)]
        if 0 < len(task_id) <= 40 and re.fullmatch(r'[A-Za-z0-9_-]+', task_id):
            return task_id
    return None


def _is_pdf_extension(ext: str) -> bool:
    return ext.lower().lstrip('.') in PDF_EXTENSIONS


def _estimate_token_count(content: str, ext: str) -> int:
    if not content:
        return 0
    encoded = len(content.encode('utf-8'))
    divisor = 3 if ext in {'json', 'ipynb'} else 4
    return int(math.ceil(encoded / float(divisor)))


async def validateContentTokens(
    content: str,
    ext: str,
    maxTokens: int | None = None,
) -> None:
    effective_max_tokens = maxTokens or getDefaultFileReadingLimits()['maxTokens']
    estimate = _estimate_token_count(content, ext)
    if estimate > effective_max_tokens:
        raise MaxFileReadTokenExceededError(estimate, effective_max_tokens)


def _add_line_numbers(content: str, start_line: int) -> str:
    if not content:
        return ''
    lines = content.splitlines()
    return '\n'.join(
        f'{line_number}\t{line}'
        for line_number, line in enumerate(lines, start=start_line)
    )


def _format_file_lines(file_data: dict[str, Any]) -> str:
    return _add_line_numbers(
        str(file_data.get('content', '')),
        int(file_data.get('startLine', 1)),
    )


def _notebook_output_to_text(output: Any) -> str:
    if not isinstance(output, dict):
        return str(output)
    if output.get('output_type') == 'stream':
        text = output.get('text', '')
        if isinstance(text, list):
            return ''.join(str(part) for part in text)
        return str(text)
    if output.get('output_type') == 'error':
        traceback = output.get('traceback') or []
        lines = [str(line) for line in traceback]
        if output.get('ename') or output.get('evalue'):
            lines.append(f"{output.get('ename', '')}: {output.get('evalue', '')}".strip(': '))
        return '\n'.join(part for part in lines if part)
    data = output.get('data')
    if isinstance(data, dict):
        for key in ('text/plain', 'text/markdown'):
            value = data.get(key)
            if isinstance(value, list):
                return ''.join(str(part) for part in value)
            if value is not None:
                return str(value)
        if any(key.startswith('image/') for key in data):
            return '[image output omitted]'
    text = output.get('text')
    if isinstance(text, list):
        return ''.join(str(part) for part in text)
    if text is not None:
        return str(text)
    return json.dumps(output, ensure_ascii=False, default=str)


def _notebook_cells_to_text(cells: list[Any]) -> str:
    parts: list[str] = []
    for index, cell in enumerate(cells, start=1):
        if not isinstance(cell, dict):
            parts.append(f'[Cell {index}]\n{cell}')
            continue
        cell_type = str(cell.get('cell_type', 'unknown'))
        source = cell.get('source', '')
        if isinstance(source, list):
            source_text = ''.join(str(part) for part in source)
        else:
            source_text = str(source)
        parts.append(f'[Cell {index}: {cell_type}]\n{source_text.rstrip()}')
        outputs = cell.get('outputs')
        if isinstance(outputs, list) and outputs:
            output_texts = [
                _notebook_output_to_text(item).rstrip()
                for item in outputs
                if _notebook_output_to_text(item).strip()
            ]
            if output_texts:
                parts.append(f'[Cell {index} output]\n' + '\n\n'.join(output_texts))
    return '\n\n'.join(part for part in parts if part.strip())


def _estimate_pdf_page_count(path: Path, raw: bytes | None = None) -> int | None:
    pdfinfo = shutil.which('pdfinfo')
    if pdfinfo:
        try:
            completed = subprocess.run(
                [pdfinfo, str(path)],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if completed.returncode == 0:
                match = re.search(r'^Pages:\s+(\d+)\s*$', completed.stdout, re.MULTILINE)
                if match:
                    return int(match.group(1))
        except OSError:
            pass
    raw_bytes = raw if raw is not None else path.read_bytes()
    matches = re.findall(rb'/Type\s*/Page\b', raw_bytes)
    return len(matches) or None


def _extract_pdf_pages(
    file_path: Path,
    page_range: tuple[int, int] | None,
    original_file_path: str,
) -> dict[str, Any]:
    pdftoppm = shutil.which('pdftoppm')
    if not pdftoppm:
        raise RuntimeError(
            'Reading specific PDF page ranges requires poppler-utils '
            '(pdftoppm/pdfinfo). Install poppler and try again.'
        )
    output_root = Path(
        tempfile.mkdtemp(prefix='file_read_pdf_', dir=str(STATE_ROOT))
    )
    prefix = output_root / 'page'
    command = [pdftoppm, '-jpeg']
    if page_range is not None:
        command.extend(['-f', str(page_range[0]), '-l', str(page_range[1])])
    command.extend([str(file_path), str(prefix)])
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(stderr or 'Failed to extract PDF pages.')
    generated = sorted(output_root.glob('page-*.jpg'))
    if not generated:
        raise RuntimeError('PDF page extraction completed but produced no page images.')
    return {
        'type': 'parts',
        'file': {
            'filePath': original_file_path,
            'originalSize': file_path.stat().st_size,
            'count': len(generated),
            'outputDir': str(output_root),
        },
    }


def _read_text_in_range(
    path: Path,
    offset: int,
    limit: int | None,
    max_size_bytes: int | None,
) -> dict[str, Any]:
    stats = path.stat()
    if max_size_bytes is not None and stats.st_size > max_size_bytes:
        raise ValueError(
            f'File content ({_format_file_size(stats.st_size)}) exceeds maximum '
            f'allowed size ({_format_file_size(max_size_bytes)}). Use offset and '
            'limit parameters to read a smaller portion of the file.'
        )

    selected_lines: list[str] = []
    total_lines = 0
    returned_lines = 0

    with path.open('r', encoding='utf-8', errors='replace', newline='') as handle:
        for index, line in enumerate(handle):
            total_lines += 1
            if index < offset:
                continue
            if limit is None or returned_lines < limit:
                selected_lines.append(line)
                returned_lines += 1

    content = ''.join(selected_lines)
    return {
        'content': content,
        'lineCount': returned_lines,
        'totalLines': total_lines,
        'totalBytes': stats.st_size,
        'readBytes': len(content.encode('utf-8')),
        'mtimeMs': int(stats.st_mtime_ns // 1_000_000),
    }


def _create_image_response(
    buffer: bytes,
    media_type: str,
    original_size: int,
    dimensions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        'base64': base64.b64encode(buffer).decode('ascii'),
        'type': media_type if media_type.startswith('image/') else f'image/{media_type}',
        'originalSize': original_size,
    }
    if dimensions:
        payload['dimensions'] = dimensions
    return {'type': 'image', 'file': payload}


def readImageWithTokenBudget(
    file_path: str,
    maxTokens: int = getDefaultFileReadingLimits()['maxTokens'],
    maxBytes: int | None = None,
) -> dict[str, Any]:
    path = Path(file_path)
    if maxBytes is not None and path.stat().st_size > maxBytes:
        raise ValueError(
            f'Image content ({_format_file_size(path.stat().st_size)}) exceeds '
            f'maximum allowed size ({_format_file_size(maxBytes)}).'
        )

    image_buffer = path.read_bytes()
    original_size = len(image_buffer)
    if original_size == 0:
        raise ValueError(f'Image file is empty: {file_path}')

    detected_media_type = detect_image_media_type(image_buffer)
    detected_format = detected_media_type.split('/', 1)[-1] or 'png'

    try:
        resized = maybe_resize_and_downsample_image_bytes(
            image_buffer,
            original_size,
            detected_format,
        )
        result = _create_image_response(
            resized['buffer'],
            resized['mediaType'],
            original_size,
            resized.get('dimensions'),
        )
    except Exception:
        result = _create_image_response(image_buffer, detected_media_type, original_size)

    estimated_tokens = int(math.ceil(len(result['file']['base64']) * 0.125))
    if estimated_tokens > maxTokens:
        compressed = compress_image_with_token_limit(
            image_buffer,
            maxTokens,
            detected_media_type,
        )
        return {
            'type': 'image',
            'file': {
                'base64': compressed['base64'],
                'type': compressed['mediaType'],
                'originalSize': original_size,
                **(
                    {'dimensions': compressed['dimensions']}
                    if compressed.get('dimensions')
                    else {}
                ),
            },
        }

    return result


class PythonFileReadTool:
    name = FILE_READ_TOOL_NAME
    search_hint = 'read files, images, PDFs, notebooks'
    max_result_size_chars = 1_000_000_000
    strict = True
    input_schema = {
        'file_path': 'absolute path to the file to read',
        'offset': 'optional 1-based starting line number',
        'limit': 'optional maximum number of lines to return',
        'pages': 'optional page range for PDF files, for example 1-5',
    }
    output_schema = {
        'type': 'text, image, notebook, pdf, parts, or file_unchanged',
        'file': 'payload for the specific output type',
    }

    async def description(self, _input_data: dict[str, Any] | None = None) -> str:
        return DESCRIPTION

    async def prompt(self) -> str:
        limits = getDefaultFileReadingLimits()
        max_size_instruction = (
            '. Files larger than '
            f"{_format_file_size(int(limits['maxSizeBytes']))} will return an error; "
            'use offset and limit for larger files'
        )
        offset_instruction = (
            OFFSET_INSTRUCTION_TARGETED
            if limits.get('targetedRangeNudge')
            else OFFSET_INSTRUCTION_DEFAULT
        )
        return renderPromptTemplate(
            LINE_FORMAT_INSTRUCTION,
            max_size_instruction,
            offset_instruction,
        )

    def userFacingName(self, input_data: dict[str, Any] | None = None) -> str:
        file_path = str((input_data or {}).get('file_path', ''))
        if file_path.startswith(str(PLAN_ROOT)):
            return 'Reading Plan'
        if _get_agent_output_task_id(file_path):
            return 'Read agent output'
        return 'Read'

    def getToolUseSummary(self, input_data: dict[str, Any] | None) -> str | None:
        file_path = str((input_data or {}).get('file_path', ''))
        if not file_path:
            return None
        return _get_agent_output_task_id(file_path) or _display_path(file_path)

    def getActivityDescription(self, input_data: dict[str, Any] | None) -> str:
        summary = self.getToolUseSummary(input_data)
        return f'Reading {summary}' if summary else 'Reading file'

    def isConcurrencySafe(self) -> bool:
        return True

    def isReadOnly(self) -> bool:
        return True

    def toAutoClassifierInput(self, input_data: dict[str, Any]) -> str:
        return str(input_data.get('file_path', ''))

    def getPath(self, input_data: dict[str, Any]) -> str:
        return str(input_data.get('file_path', '') or os.getcwd())

    def backfillObservableInput(self, input_data: dict[str, Any]) -> None:
        file_path = input_data.get('file_path')
        if isinstance(file_path, str) and file_path:
            input_data['file_path'] = expand_path(file_path)

    async def preparePermissionMatcher(self, payload: dict[str, Any]):
        file_path = expand_path(str(payload.get('file_path', '')))

        def _matcher(pattern: str) -> bool:
            return _match_wildcard_pattern(pattern, file_path)

        return _matcher

    async def checkPermissions(
        self,
        input_data: dict[str, Any],
        context: ToolUseContext | None = None,
    ) -> dict[str, Any]:
        file_path = expand_path(
            str(input_data.get('file_path', '')),
            context.options.cwd if context is not None else None,
        )
        permission_context = _get_permission_context(context)
        deny_rule = _matching_rule_for_input(
            file_path,
            permission_context,
            behavior='deny',
        )
        if deny_rule is not None:
            return {
                'behavior': 'deny',
                'message': (
                    'File is in a directory that is denied by your permission settings.'
                ),
                'decisionReason': {
                    'type': 'rule',
                    'rule': deny_rule,
                    'behavior': 'deny',
                },
            }
        return {'behavior': 'allow', 'updatedInput': input_data}

    def extractSearchText(self, _output: dict[str, Any]) -> str:
        return ''

    async def validateInput(
        self,
        input_data: dict[str, Any],
        toolUseContext: ToolUseContext | None = None,
    ) -> dict[str, Any]:
        file_path = str(input_data.get('file_path', '')).strip()
        if not file_path:
            return {
                'result': False,
                'message': 'file_path is required.',
                'errorCode': 1,
            }

        offset = input_data.get('offset')
        if offset is not None:
            try:
                offset_value = int(offset)
            except (TypeError, ValueError):
                return {
                    'result': False,
                    'message': 'offset must be a non-negative integer.',
                    'errorCode': 2,
                }
            if offset_value < 0:
                return {
                    'result': False,
                    'message': 'offset must be a non-negative integer.',
                    'errorCode': 2,
                }

        limit = input_data.get('limit')
        if limit is not None:
            try:
                limit_value = int(limit)
            except (TypeError, ValueError):
                return {
                    'result': False,
                    'message': 'limit must be a positive integer.',
                    'errorCode': 3,
                }
            if limit_value <= 0:
                return {
                    'result': False,
                    'message': 'limit must be a positive integer.',
                    'errorCode': 3,
                }

        pages = input_data.get('pages')
        if pages is not None:
            parsed = _parse_pdf_page_range(str(pages))
            if parsed is None:
                return {
                    'result': False,
                    'message': (
                        f'Invalid pages parameter: "{pages}". Use formats like '
                        '"1-5", "3", or "10-20". Pages are 1-indexed.'
                    ),
                    'errorCode': 7,
                }
            first_page, last_page = parsed
            if last_page - first_page + 1 > PDF_MAX_PAGES_PER_READ:
                return {
                    'result': False,
                    'message': (
                        f'Page range "{pages}" exceeds maximum of '
                        f'{PDF_MAX_PAGES_PER_READ} pages per request.'
                    ),
                    'errorCode': 8,
                }

        full_file_path = expand_path(
            file_path,
            toolUseContext.options.cwd if toolUseContext is not None else None,
        )
        permission_context = _get_permission_context(toolUseContext)
        deny_rule = _matching_rule_for_input(
            full_file_path,
            permission_context,
            behavior='deny',
        )
        if deny_rule is not None:
            return {
                'result': False,
                'message': (
                    'File is in a directory that is denied by your permission settings.'
                ),
                'errorCode': 1,
            }

        if full_file_path.startswith('\\\\') or full_file_path.startswith('//'):
            return {'result': True}

        ext = Path(full_file_path).suffix.lower()
        if (
            ext in BINARY_EXTENSIONS
            and ext not in {'.pdf', '.svg'}
            and ext.lstrip('.') not in IMAGE_EXTENSIONS
        ):
            return {
                'result': False,
                'message': (
                    'This tool cannot read binary files. The file appears to be a '
                    f'binary {ext} file.'
                ),
                'errorCode': 4,
            }

        if isBlockedDevicePath(full_file_path):
            return {
                'result': False,
                'message': (
                    f"Cannot read '{file_path}': this device file would block or "
                    'produce infinite output.'
                ),
                'errorCode': 9,
            }

        return {'result': True}

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
        payload.setdefault('offset', 1)

        context = toolUseContext or ToolUseContext()
        validation = await self.validateInput(payload, context)
        if not validation.get('result'):
            raise ValueError(str(validation.get('message', 'Invalid file read request.')))

        file_path = str(payload.get('file_path', ''))
        offset = int(payload.get('offset', 1))
        limit = payload.get('limit')
        limit_value = None if limit is None else int(limit)
        pages = payload.get('pages')

        defaults = getDefaultFileReadingLimits()
        context_limits = getattr(context, 'fileReadingLimits', None)
        if not isinstance(context_limits, dict):
            context_limits = {}
        max_size_bytes = int(context_limits.get('maxSizeBytes', defaults['maxSizeBytes']))
        max_tokens = int(context_limits.get('maxTokens', defaults['maxTokens']))

        full_file_path = expand_path(file_path, context.options.cwd)
        ext = Path(full_file_path).suffix.lower().lstrip('.')

        existing_state = context.read_file_state.get(full_file_path)
        if (
            existing_state
            and not bool(existing_state.get('isPartialView'))
            and existing_state.get('offset') is not None
            and existing_state.get('offset') == offset
            and existing_state.get('limit') == limit_value
        ):
            try:
                if _get_file_modification_time(Path(full_file_path)) == int(
                    existing_state.get('timestamp', -1)
                ):
                    return {
                        'data': {
                            'type': 'file_unchanged',
                            'file': {'filePath': file_path},
                        }
                    }
            except OSError:
                pass

        try:
            data = await self._call_inner(
                file_path=file_path,
                full_file_path=full_file_path,
                resolved_file_path=full_file_path,
                ext=ext,
                offset=offset,
                limit=limit_value,
                pages=str(pages) if pages is not None else None,
                max_size_bytes=max_size_bytes,
                max_tokens=max_tokens,
                context=context,
            )
            return {'data': data}
        except FileNotFoundError:
            alternate_path = getAlternateScreenshotPath(full_file_path)
            if alternate_path:
                try:
                    data = await self._call_inner(
                        file_path=file_path,
                        full_file_path=full_file_path,
                        resolved_file_path=alternate_path,
                        ext=ext,
                        offset=offset,
                        limit=limit_value,
                        pages=str(pages) if pages is not None else None,
                        max_size_bytes=max_size_bytes,
                        max_tokens=max_tokens,
                        context=context,
                    )
                    return {'data': data}
                except FileNotFoundError:
                    pass

            target = Path(full_file_path)
            similar_filename = _find_similar_file(target)
            cwd_suggestion = _suggest_path_under_cwd(target, context.options.cwd)
            message = f'File does not exist. {FILE_NOT_FOUND_CWD_NOTE} {context.options.cwd}.'
            if cwd_suggestion:
                message += f' Did you mean {cwd_suggestion}?'
            elif similar_filename:
                message += f' Did you mean {similar_filename}?'
            raise ValueError(message)

    async def _call_inner(
        self,
        *,
        file_path: str,
        full_file_path: str,
        resolved_file_path: str,
        ext: str,
        offset: int,
        limit: int | None,
        pages: str | None,
        max_size_bytes: int,
        max_tokens: int,
        context: ToolUseContext,
    ) -> dict[str, Any]:
        target = Path(resolved_file_path)
        if not target.exists():
            raise FileNotFoundError(resolved_file_path)
        if target.is_dir():
            raise ValueError(
                f'{file_path} is a directory. Use the {BASH_TOOL_NAME} tool to inspect directories.'
            )

        if ext == 'ipynb':
            notebook = json.loads(target.read_text(encoding='utf-8', errors='replace'))
            cells = notebook.get('cells', [])
            if not isinstance(cells, list):
                cells = []
            cells_json = json.dumps(cells, ensure_ascii=False, default=str)
            cells_json_bytes = len(cells_json.encode('utf-8'))
            if cells_json_bytes > max_size_bytes:
                raise ValueError(
                    f'Notebook content ({_format_file_size(cells_json_bytes)}) exceeds '
                    f'maximum allowed size ({_format_file_size(max_size_bytes)}). '
                    f'Use {BASH_TOOL_NAME} with jq to read specific notebook sections.'
                )
            await validateContentTokens(cells_json, ext, max_tokens)
            context.read_file_state[full_file_path] = {
                'content': cells_json,
                'timestamp': _get_file_modification_time(target),
                'offset': offset,
                'limit': limit,
                'isPartialView': False,
            }
            return {
                'type': 'notebook',
                'file': {
                    'filePath': file_path,
                    'cells': cells,
                },
            }

        if ext in IMAGE_EXTENSIONS:
            return readImageWithTokenBudget(
                resolved_file_path,
                maxTokens=max_tokens,
                maxBytes=max(max_size_bytes * 8, 4 * 1024 * 1024),
            )

        if _is_pdf_extension(ext):
            raw_pdf = target.read_bytes()
            original_size = len(raw_pdf)
            if pages is not None:
                parsed_range = _parse_pdf_page_range(pages)
                if parsed_range is None:
                    raise ValueError(f'Invalid pages parameter: {pages}')
                page_count = _estimate_pdf_page_count(target, raw_pdf)
                if page_count is not None and parsed_range[1] > page_count:
                    raise ValueError(
                        f'Page range "{pages}" exceeds the PDF page count ({page_count}).'
                    )
                return _extract_pdf_pages(target, parsed_range, file_path)

            page_count = _estimate_pdf_page_count(target, raw_pdf)
            if page_count is not None and page_count > PDF_AT_MENTION_INLINE_THRESHOLD:
                raise ValueError(
                    f'This PDF has {page_count} pages, which is too many to read at once. '
                    'Use the pages parameter to read specific page ranges '
                    '(for example, pages: "1-5").'
                )
            if original_size > MAX_INLINE_PDF_BYTES:
                raise ValueError(
                    f'This PDF is too large to inline ({_format_file_size(original_size)}). '
                    'Use the pages parameter to read specific page ranges.'
                )
            return {
                'type': 'pdf',
                'file': {
                    'filePath': file_path,
                    'base64': base64.b64encode(raw_pdf).decode('ascii'),
                    'originalSize': original_size,
                },
            }

        line_offset = 0 if offset == 0 else max(offset - 1, 0)
        text_result = _read_text_in_range(
            target,
            line_offset,
            limit,
            None if limit is not None else max_size_bytes,
        )
        await validateContentTokens(str(text_result['content']), ext, max_tokens)

        context.read_file_state[full_file_path] = {
            'content': text_result['content'],
            'timestamp': int(text_result['mtimeMs']),
            'offset': offset,
            'limit': limit,
            'isPartialView': bool(offset not in (None, 1) or limit is not None),
        }

        for listener in list(_FILE_READ_LISTENERS):
            listener(resolved_file_path, str(text_result['content']))

        return {
            'type': 'text',
            'file': {
                'filePath': file_path,
                'content': text_result['content'],
                'numLines': int(text_result['lineCount']),
                'startLine': offset,
                'totalLines': int(text_result['totalLines']),
            },
        }

    def mapToolResultToToolResultBlockParam(
        self,
        output: dict[str, Any],
        tool_use_id: str,
    ) -> dict[str, Any]:
        output_type = output.get('type')
        file_data = output.get('file', {})

        if output_type == 'image':
            return {
                'tool_use_id': tool_use_id,
                'type': 'tool_result',
                'content': [
                    {
                        'type': 'image',
                        'source': {
                            'type': 'base64',
                            'data': file_data.get('base64', ''),
                            'media_type': file_data.get('type', 'image/png'),
                        },
                    }
                ],
            }

        if output_type == 'notebook':
            content = _notebook_cells_to_text(list(file_data.get('cells', [])))
            if not content.strip():
                content = (
                    '<system-reminder>Warning: the notebook exists but contains no cells.'
                    '</system-reminder>'
                )
            return {
                'tool_use_id': tool_use_id,
                'type': 'tool_result',
                'content': content,
            }

        if output_type == 'pdf':
            return {
                'tool_use_id': tool_use_id,
                'type': 'tool_result',
                'content': (
                    f"PDF file read: {file_data.get('filePath', '')} "
                    f"({_format_file_size(int(file_data.get('originalSize', 0)))})"
                ),
            }

        if output_type == 'parts':
            return {
                'tool_use_id': tool_use_id,
                'type': 'tool_result',
                'content': (
                    f"PDF pages extracted: {file_data.get('count', 0)} page(s) from "
                    f"{file_data.get('filePath', '')} "
                    f"({_format_file_size(int(file_data.get('originalSize', 0)))})\n"
                    f"Output directory: {file_data.get('outputDir', '')}"
                ),
            }

        if output_type == 'file_unchanged':
            return {
                'tool_use_id': tool_use_id,
                'type': 'tool_result',
                'content': FILE_UNCHANGED_STUB,
            }

        content = str(file_data.get('content', ''))
        if content:
            rendered = _format_file_lines(file_data) + CYBER_RISK_MITIGATION_REMINDER
        else:
            total_lines = int(file_data.get('totalLines', 0))
            start_line = int(file_data.get('startLine', 1))
            if total_lines == 0:
                rendered = (
                    '<system-reminder>Warning: the file exists but the contents '
                    'are empty.</system-reminder>'
                )
            else:
                rendered = (
                    '<system-reminder>Warning: the file exists but is shorter than '
                    f'the provided offset ({start_line}). The file has {total_lines} '
                    'lines.</system-reminder>'
                )
        return {
            'tool_use_id': tool_use_id,
            'type': 'tool_result',
            'content': rendered,
        }


FileReadTool = PythonFileReadTool()

__all__ = [
    'FileReadTool',
    'MaxFileReadTokenExceededError',
    'PythonFileReadTool',
    'readImageWithTokenBudget',
    'registerFileReadListener',
]
