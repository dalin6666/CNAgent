from __future__ import annotations

import re
import secrets
import shlex
from typing import TypedDict


class SedEditInfo(TypedDict):
    filePath: str
    pattern: str
    replacement: str
    flags: str
    extendedRegex: bool


_BACKSLASH_PLACEHOLDER = "\x00BACKSLASH\x00"
_PLUS_PLACEHOLDER = "\x00PLUS\x00"
_QUESTION_PLACEHOLDER = "\x00QUESTION\x00"
_PIPE_PLACEHOLDER = "\x00PIPE\x00"
_LPAREN_PLACEHOLDER = "\x00LPAREN\x00"
_RPAREN_PLACEHOLDER = "\x00RPAREN\x00"


def isSedInPlaceEdit(command: str) -> bool:
    return parseSedEditCommand(command) is not None


def parseSedEditCommand(command: str) -> SedEditInfo | None:
    trimmed = command.strip()
    sed_match = re.match(r"^\s*sed\s+", trimmed)
    if not sed_match:
        return None
    try:
        args = shlex.split(trimmed[sed_match.end() :], posix=True)
    except ValueError:
        return None
    has_in_place_flag = False
    extended_regex = False
    expression: str | None = None
    file_path: str | None = None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in {"-i", "--in-place"}:
            has_in_place_flag = True
            i += 1
            if i < len(args):
                next_arg = args[i]
                if next_arg == "" or (not next_arg.startswith("-") and next_arg.startswith(".")):
                    i += 1
            continue
        if arg.startswith("-i"):
            has_in_place_flag = True
            i += 1
            continue
        if arg in {"-E", "-r", "--regexp-extended"}:
            extended_regex = True
            i += 1
            continue
        if arg in {"-e", "--expression"}:
            if expression is not None or i + 1 >= len(args):
                return None
            expression = args[i + 1]
            i += 2
            continue
        if arg.startswith("--expression="):
            if expression is not None:
                return None
            expression = arg.split("=", 1)[1]
            i += 1
            continue
        if arg.startswith("-"):
            return None
        if expression is None:
            expression = arg
        elif file_path is None:
            file_path = arg
        else:
            return None
        i += 1
    if not has_in_place_flag or not expression or not file_path:
        return None
    subst_match = re.match(r"^s/", expression)
    if not subst_match:
        return None
    rest = expression[2:]
    pattern = ""
    replacement = ""
    flags = ""
    state = "pattern"
    j = 0
    while j < len(rest):
        char = rest[j]
        if char == "\\" and j + 1 < len(rest):
            target = rest[j : j + 2]
            if state == "pattern":
                pattern += target
            elif state == "replacement":
                replacement += target
            else:
                flags += target
            j += 2
            continue
        if char == "/":
            if state == "pattern":
                state = "replacement"
            elif state == "replacement":
                state = "flags"
            else:
                return None
            j += 1
            continue
        if state == "pattern":
            pattern += char
        elif state == "replacement":
            replacement += char
        else:
            flags += char
        j += 1
    if state != "flags" or not re.fullmatch(r"[gpimIM1-9]*", flags):
        return None
    return {
        "filePath": file_path,
        "pattern": pattern,
        "replacement": replacement,
        "flags": flags,
        "extendedRegex": extended_regex,
    }


def applySedSubstitution(content: str, sedInfo: SedEditInfo) -> str:
    regex_flags = ""
    if "g" in sedInfo["flags"]:
        regex_flags += "g"
    if "i" in sedInfo["flags"] or "I" in sedInfo["flags"]:
        regex_flags += "i"
    if "m" in sedInfo["flags"] or "M" in sedInfo["flags"]:
        regex_flags += "m"
    js_pattern = sedInfo["pattern"].replace(r"\/", "/")
    if not sedInfo["extendedRegex"]:
        js_pattern = (
            js_pattern.replace(r"\\", _BACKSLASH_PLACEHOLDER)
            .replace(r"\+", _PLUS_PLACEHOLDER)
            .replace(r"\?", _QUESTION_PLACEHOLDER)
            .replace(r"\|", _PIPE_PLACEHOLDER)
            .replace(r"\(", _LPAREN_PLACEHOLDER)
            .replace(r"\)", _RPAREN_PLACEHOLDER)
            .replace("+", r"\+")
            .replace("?", r"\?")
            .replace("|", r"\|")
            .replace("(", r"\(")
            .replace(")", r"\)")
            .replace(_BACKSLASH_PLACEHOLDER, r"\\")
            .replace(_PLUS_PLACEHOLDER, "+")
            .replace(_QUESTION_PLACEHOLDER, "?")
            .replace(_PIPE_PLACEHOLDER, "|")
            .replace(_LPAREN_PLACEHOLDER, "(")
            .replace(_RPAREN_PLACEHOLDER, ")")
        )
    escaped_amp_placeholder = f"___ESCAPED_AMPERSAND_{secrets.token_hex(8)}___"
    replacement = (
        sedInfo["replacement"]
        .replace(r"\/", "/")
        .replace(r"\&", escaped_amp_placeholder)
        .replace("&", r"\g<0>")
        .replace(escaped_amp_placeholder, "&")
    )
    count = 0 if "g" in regex_flags else 1
    python_flags = 0
    if "i" in regex_flags:
        python_flags |= re.IGNORECASE
    if "m" in regex_flags:
        python_flags |= re.MULTILINE
    try:
        return re.sub(js_pattern, replacement, content, count=count, flags=python_flags)
    except re.error:
        return content


__all__ = ["SedEditInfo", "applySedSubstitution", "isSedInPlaceEdit", "parseSedEditCommand"]
