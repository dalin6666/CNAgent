from __future__ import annotations

from typing import Callable

from .bashCommandHelpers import split_command_deprecated

CommandSemantic = Callable[[int, str, str], dict[str, object]]


def _default_semantic(exit_code: int, _stdout: str, _stderr: str) -> dict[str, object]:
    return {
        "isError": exit_code != 0,
        "message": f"Command failed with exit code {exit_code}" if exit_code != 0 else None,
    }


COMMAND_SEMANTICS: dict[str, CommandSemantic] = {
    "grep": lambda exit_code, _stdout, _stderr: {
        "isError": exit_code >= 2,
        "message": "No matches found" if exit_code == 1 else None,
    },
    "rg": lambda exit_code, _stdout, _stderr: {
        "isError": exit_code >= 2,
        "message": "No matches found" if exit_code == 1 else None,
    },
    "find": lambda exit_code, _stdout, _stderr: {
        "isError": exit_code >= 2,
        "message": "Some directories were inaccessible" if exit_code == 1 else None,
    },
    "diff": lambda exit_code, _stdout, _stderr: {
        "isError": exit_code >= 2,
        "message": "Files differ" if exit_code == 1 else None,
    },
    "test": lambda exit_code, _stdout, _stderr: {
        "isError": exit_code >= 2,
        "message": "Condition is false" if exit_code == 1 else None,
    },
    "[": lambda exit_code, _stdout, _stderr: {
        "isError": exit_code >= 2,
        "message": "Condition is false" if exit_code == 1 else None,
    },
}


def _extract_base_command(command: str) -> str:
    return (command.strip().split() or [""])[0]


def _heuristically_extract_base_command(command: str) -> str:
    segments = split_command_deprecated(command)
    return _extract_base_command(segments[-1] if segments else command)


def interpretCommandResult(
    command: str,
    exitCode: int,
    stdout: str,
    stderr: str,
) -> dict[str, object]:
    base_command = _heuristically_extract_base_command(command)
    semantic = COMMAND_SEMANTICS.get(base_command, _default_semantic)
    result = semantic(exitCode, stdout, stderr)
    return {"isError": bool(result.get("isError")), "message": result.get("message")}


__all__ = ["CommandSemantic", "interpretCommandResult"]
