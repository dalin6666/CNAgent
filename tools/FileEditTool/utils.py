from __future__ import annotations

import codecs
import difflib
import re
import unicodedata
from pathlib import Path

from .._runtime import expand_path
from .types import EditInput, FileEdit, Hunk

LEFT_SINGLE_CURLY_QUOTE = '\u2018'
RIGHT_SINGLE_CURLY_QUOTE = '\u2019'
LEFT_DOUBLE_CURLY_QUOTE = '\u201c'
RIGHT_DOUBLE_CURLY_QUOTE = '\u201d'

DIFF_SNIPPET_MAX_BYTES = 8192
CONTEXT_LINES = 4
PATCH_CONTEXT_LINES = 3

_HUNK_HEADER_RE = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')
_DESANITIZATIONS: dict[str, str] = {
    '<fnr>': '<function_results>',
    '<n>': '<name>',
    '</n>': '</name>',
    '<o>': '<output>',
    '</o>': '</output>',
    '<e>': '<error>',
    '</e>': '</error>',
    '<s>': '<system>',
    '</s>': '</system>',
    '<r>': '<result>',
    '</r>': '</result>',
    '< META_START >': '<META_START>',
    '< META_END >': '<META_END>',
    '< EOT >': '<EOT>',
    '< META >': '<META>',
    '< SOS >': '<SOS>',
    '\n\nH:': '\n\nHuman:',
    '\n\nA:': '\n\nAssistant:',
}


def normalizeQuotes(value: str) -> str:
    return (
        value.replace(LEFT_SINGLE_CURLY_QUOTE, "'")
        .replace(RIGHT_SINGLE_CURLY_QUOTE, "'")
        .replace(LEFT_DOUBLE_CURLY_QUOTE, '"')
        .replace(RIGHT_DOUBLE_CURLY_QUOTE, '"')
    )


def stripTrailingWhitespace(value: str) -> str:
    parts = re.split(r'(\r\n|\n|\r)', value)
    result: list[str] = []
    for index, part in enumerate(parts):
        if index % 2 == 0:
            result.append(re.sub(r'\s+$', '', part))
        else:
            result.append(part)
    return ''.join(result)


def findActualString(fileContent: str, searchString: str) -> str | None:
    if searchString in fileContent:
        return searchString

    normalized_search = normalizeQuotes(searchString)
    normalized_file = normalizeQuotes(fileContent)
    search_index = normalized_file.find(normalized_search)
    if search_index == -1:
        return None
    return fileContent[search_index : search_index + len(searchString)]


def preserveQuoteStyle(oldString: str, actualOldString: str, newString: str) -> str:
    if oldString == actualOldString:
        return newString

    has_double_quotes = (
        LEFT_DOUBLE_CURLY_QUOTE in actualOldString
        or RIGHT_DOUBLE_CURLY_QUOTE in actualOldString
    )
    has_single_quotes = (
        LEFT_SINGLE_CURLY_QUOTE in actualOldString
        or RIGHT_SINGLE_CURLY_QUOTE in actualOldString
    )

    result = newString
    if has_double_quotes:
        result = _apply_curly_double_quotes(result)
    if has_single_quotes:
        result = _apply_curly_single_quotes(result)
    return result


def applyEditToFile(
    originalContent: str,
    oldString: str,
    newString: str,
    replaceAll: bool = False,
) -> str:
    if oldString == '':
        return newString

    if newString != '':
        if replaceAll:
            return originalContent.replace(oldString, newString)
        return originalContent.replace(oldString, newString, 1)

    strip_trailing_newline = (
        not oldString.endswith('\n')
        and f'{oldString}\n' in originalContent
    )
    if strip_trailing_newline:
        if replaceAll:
            return originalContent.replace(f'{oldString}\n', newString)
        return originalContent.replace(f'{oldString}\n', newString, 1)
    if replaceAll:
        return originalContent.replace(oldString, newString)
    return originalContent.replace(oldString, newString, 1)


def getPatchForEdit(
    *,
    filePath: str,
    fileContents: str,
    oldString: str,
    newString: str,
    replaceAll: bool = False,
) -> dict[str, object]:
    return getPatchForEdits(
        filePath=filePath,
        fileContents=fileContents,
        edits=[
            {
                'old_string': oldString,
                'new_string': newString,
                'replace_all': replaceAll,
            }
        ],
    )


def getPatchForEdits(
    *,
    filePath: str,
    fileContents: str,
    edits: list[FileEdit],
) -> dict[str, object]:
    updated_file = fileContents
    applied_new_strings: list[str] = []

    if (
        not fileContents
        and len(edits) == 1
        and edits[0]['old_string'] == ''
        and edits[0]['new_string'] == ''
    ):
        patch = _structured_patch(filePath, fileContents, '', context=PATCH_CONTEXT_LINES)
        return {'patch': patch, 'updatedFile': ''}

    for edit in edits:
        old_string_to_check = re.sub(r'\n+$', '', edit['old_string'])
        for previous_new_string in applied_new_strings:
            if old_string_to_check and old_string_to_check in previous_new_string:
                raise ValueError(
                    'Cannot edit file: old_string is a substring of a new_string from a previous edit.'
                )

        previous_content = updated_file
        updated_file = (
            edit['new_string']
            if edit['old_string'] == ''
            else applyEditToFile(
                updated_file,
                edit['old_string'],
                edit['new_string'],
                edit['replace_all'],
            )
        )
        if updated_file == previous_content:
            raise ValueError('String not found in file. Failed to apply edit.')
        applied_new_strings.append(edit['new_string'])

    if updated_file == fileContents:
        raise ValueError('Original and edited file match exactly. Failed to apply edit.')

    patch = _structured_patch(
        filePath,
        _convert_leading_tabs_to_spaces(fileContents),
        _convert_leading_tabs_to_spaces(updated_file),
        context=PATCH_CONTEXT_LINES,
    )
    return {'patch': patch, 'updatedFile': updated_file}


def getSnippetForTwoFileDiff(fileAContents: str, fileBContents: str) -> str:
    patch = _structured_patch('file.txt', fileAContents, fileBContents, context=8)
    full = '\n...\n'.join(
        _add_line_numbers(
            '\n'.join(
                line[1:]
                for line in hunk['lines']
                if not line.startswith('-') and not line.startswith('\\')
            ),
            hunk['oldStart'],
        )
        for hunk in patch
    )
    if len(full.encode('utf-8')) <= DIFF_SNIPPET_MAX_BYTES:
        return full

    cutoff = full.rfind('\n', 0, DIFF_SNIPPET_MAX_BYTES)
    kept = full[:cutoff] if cutoff > 0 else full[:DIFF_SNIPPET_MAX_BYTES]
    remaining_lines = full[len(kept) :].count('\n') + 1
    return f'{kept}\n\n... [{remaining_lines} lines truncated] ...'


def getSnippetForPatch(
    patch: list[Hunk],
    newFile: str,
) -> dict[str, object]:
    if not patch:
        return {'formattedSnippet': '', 'startLine': 1}

    min_line = min(hunk['oldStart'] for hunk in patch)
    max_line = max(hunk['oldStart'] + max(hunk['newLines'], 1) - 1 for hunk in patch)
    start_line = max(1, min_line - CONTEXT_LINES)
    end_line = max_line + CONTEXT_LINES
    file_lines = re.split(r'\r\n|\n|\r', newFile)
    snippet = '\n'.join(file_lines[start_line - 1 : end_line])
    return {
        'formattedSnippet': _add_line_numbers(snippet, start_line),
        'startLine': start_line,
    }


def getSnippet(
    originalFile: str,
    oldString: str,
    newString: str,
    contextLines: int = 4,
) -> dict[str, object]:
    before = originalFile.split(oldString, 1)[0] if oldString else ''
    replacement_line = len(re.split(r'\r\n|\n|\r', before)) - 1
    new_file_lines = re.split(
        r'\r\n|\n|\r',
        applyEditToFile(originalFile, oldString, newString),
    )
    start_line = max(0, replacement_line - contextLines)
    end_line = replacement_line + contextLines + len(re.split(r'\r\n|\n|\r', newString))
    snippet = '\n'.join(new_file_lines[start_line:end_line])
    return {'snippet': snippet, 'startLine': start_line + 1}


def getEditsForPatch(patch: list[Hunk]) -> list[FileEdit]:
    edits: list[FileEdit] = []
    for hunk in patch:
        old_lines: list[str] = []
        new_lines: list[str] = []
        for line in hunk['lines']:
            if line.startswith(' '):
                old_lines.append(line[1:])
                new_lines.append(line[1:])
            elif line.startswith('-'):
                old_lines.append(line[1:])
            elif line.startswith('+'):
                new_lines.append(line[1:])
        edits.append(
            {
                'old_string': '\n'.join(old_lines),
                'new_string': '\n'.join(new_lines),
                'replace_all': False,
            }
        )
    return edits


def normalizeFileEditInput(
    payload: dict[str, object],
) -> dict[str, object]:
    file_path = str(payload.get('file_path', ''))
    edits = list(payload.get('edits', []))
    if not edits:
        return {'file_path': file_path, 'edits': edits}

    is_markdown = file_path.lower().endswith(('.md', '.mdx'))
    try:
        full_path = Path(expand_path(file_path))
        file_content = _read_text_with_best_effort(full_path)
    except OSError:
        return {'file_path': file_path, 'edits': edits}

    normalized_edits: list[EditInput] = []
    for raw_edit in edits:
        edit = dict(raw_edit)
        old_string = str(edit.get('old_string', ''))
        new_string = str(edit.get('new_string', ''))
        replace_all = bool(edit.get('replace_all', False))
        normalized_new_string = new_string if is_markdown else stripTrailingWhitespace(new_string)

        if old_string in file_content:
            normalized_edits.append(
                {
                    'old_string': old_string,
                    'new_string': normalized_new_string,
                    'replace_all': replace_all,
                }
            )
            continue

        desanitized_old_string, applied_replacements = _desanitize_match_string(old_string)
        if desanitized_old_string in file_content:
            desanitized_new_string = normalized_new_string
            for old_value, new_value in applied_replacements:
                desanitized_new_string = desanitized_new_string.replace(old_value, new_value)
            normalized_edits.append(
                {
                    'old_string': desanitized_old_string,
                    'new_string': desanitized_new_string,
                    'replace_all': replace_all,
                }
            )
            continue

        normalized_edits.append(
            {
                'old_string': old_string,
                'new_string': normalized_new_string,
                'replace_all': replace_all,
            }
        )
    return {'file_path': file_path, 'edits': normalized_edits}


def areFileEditsEquivalent(
    edits1: list[FileEdit],
    edits2: list[FileEdit],
    originalContent: str,
) -> bool:
    if _edits_literal_equal(edits1, edits2):
        return True

    result1, error1 = _apply_edits_safely(edits1, originalContent)
    result2, error2 = _apply_edits_safely(edits2, originalContent)
    if error1 is not None and error2 is not None:
        return error1 == error2
    if error1 is not None or error2 is not None:
        return False
    return result1 == result2


def areFileEditsInputsEquivalent(
    input1: dict[str, object],
    input2: dict[str, object],
) -> bool:
    if input1.get('file_path') != input2.get('file_path'):
        return False

    edits1 = list(input1.get('edits', []))
    edits2 = list(input2.get('edits', []))
    if _edits_literal_equal(edits1, edits2):
        return True

    file_content = ''
    try:
        file_path = str(input1.get('file_path', ''))
        if file_path:
            file_content = _read_text_with_best_effort(Path(expand_path(file_path)))
    except OSError:
        file_content = ''

    return areFileEditsEquivalent(edits1, edits2, file_content)


def _apply_curly_double_quotes(value: str) -> str:
    chars = list(value)
    result: list[str] = []
    for index, char in enumerate(chars):
        if char == '"':
            result.append(
                LEFT_DOUBLE_CURLY_QUOTE
                if _is_opening_context(chars, index)
                else RIGHT_DOUBLE_CURLY_QUOTE
            )
        else:
            result.append(char)
    return ''.join(result)


def _apply_curly_single_quotes(value: str) -> str:
    chars = list(value)
    result: list[str] = []
    for index, char in enumerate(chars):
        if char != "'":
            result.append(char)
            continue

        previous = chars[index - 1] if index > 0 else None
        following = chars[index + 1] if index < len(chars) - 1 else None
        if _is_letter(previous) and _is_letter(following):
            result.append(RIGHT_SINGLE_CURLY_QUOTE)
            continue
        result.append(
            LEFT_SINGLE_CURLY_QUOTE
            if _is_opening_context(chars, index)
            else RIGHT_SINGLE_CURLY_QUOTE
        )
    return ''.join(result)


def _is_opening_context(chars: list[str], index: int) -> bool:
    if index == 0:
        return True
    previous = chars[index - 1]
    return previous in {' ', '\t', '\n', '\r', '(', '[', '{', '\u2014', '\u2013'}


def _is_letter(value: str | None) -> bool:
    return bool(value) and unicodedata.category(value).startswith('L')


def _structured_patch(
    file_path: str,
    old_content: str,
    new_content: str,
    *,
    context: int,
) -> list[Hunk]:
    diff_lines = list(
        difflib.unified_diff(
            old_content.splitlines(),
            new_content.splitlines(),
            fromfile=file_path,
            tofile=file_path,
            n=context,
            lineterm='',
        )
    )
    if len(diff_lines) <= 2:
        return []

    hunks: list[Hunk] = []
    current_hunk: Hunk | None = None
    for line in diff_lines[2:]:
        match = _HUNK_HEADER_RE.match(line)
        if match:
            if current_hunk is not None:
                hunks.append(current_hunk)
            current_hunk = {
                'oldStart': int(match.group(1)),
                'oldLines': int(match.group(2) or '1'),
                'newStart': int(match.group(3)),
                'newLines': int(match.group(4) or '1'),
                'lines': [],
            }
            continue
        if current_hunk is not None:
            current_hunk['lines'].append(line)
    if current_hunk is not None:
        hunks.append(current_hunk)
    return hunks


def _convert_leading_tabs_to_spaces(content: str) -> str:
    if '\t' not in content:
        return content
    return re.sub(r'^\t+', lambda match: '  ' * len(match.group(0)), content, flags=re.MULTILINE)


def _add_line_numbers(content: str, start_line: int) -> str:
    if not content:
        return ''
    return '\n'.join(
        f'{index}\t{line}'
        for index, line in enumerate(content.split('\n'), start=start_line)
    )


def _desanitize_match_string(match_string: str) -> tuple[str, list[tuple[str, str]]]:
    result = match_string
    applied_replacements: list[tuple[str, str]] = []
    for source, target in _DESANITIZATIONS.items():
        before = result
        result = result.replace(source, target)
        if before != result:
            applied_replacements.append((source, target))
    return result, applied_replacements


def _read_text_with_best_effort(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(codecs.BOM_UTF8):
        return raw[len(codecs.BOM_UTF8) :].decode('utf-8', errors='replace')
    if raw.startswith(codecs.BOM_UTF16_LE):
        return raw[len(codecs.BOM_UTF16_LE) :].decode('utf-16le', errors='replace')
    if raw.startswith(codecs.BOM_UTF16_BE):
        return raw[len(codecs.BOM_UTF16_BE) :].decode('utf-16be', errors='replace')
    return raw.decode('utf-8', errors='replace')


def _edits_literal_equal(edits1: list[object], edits2: list[object]) -> bool:
    if len(edits1) != len(edits2):
        return False
    for edit1, edit2 in zip(edits1, edits2):
        if dict(edit1) != dict(edit2):
            return False
    return True


def _apply_edits_safely(
    edits: list[FileEdit],
    original_content: str,
) -> tuple[str | None, str | None]:
    try:
        result = getPatchForEdits(
            filePath='temp',
            fileContents=original_content,
            edits=edits,
        )
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)
    return str(result['updatedFile']), None


__all__ = [
    'LEFT_DOUBLE_CURLY_QUOTE',
    'LEFT_SINGLE_CURLY_QUOTE',
    'RIGHT_DOUBLE_CURLY_QUOTE',
    'RIGHT_SINGLE_CURLY_QUOTE',
    'applyEditToFile',
    'areFileEditsEquivalent',
    'areFileEditsInputsEquivalent',
    'findActualString',
    'getEditsForPatch',
    'getPatchForEdit',
    'getPatchForEdits',
    'getSnippet',
    'getSnippetForPatch',
    'getSnippetForTwoFileDiff',
    'normalizeFileEditInput',
    'normalizeQuotes',
    'preserveQuoteStyle',
    'stripTrailingWhitespace',
]
