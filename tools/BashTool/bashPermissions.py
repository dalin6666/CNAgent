from __future__ import annotations

import fnmatch
import re
from typing import Any

from .._runtime import ToolUseContext
from .bashCommandHelpers import (
    SAFE_ENV_VARS,
    split_command_deprecated,
    strip_all_leading_env_vars,
    strip_safe_wrappers,
    strip_wrappers_from_argv,
)
from .bashSecurity import bashCommandIsSafeAsync_DEPRECATED, bashCommandIsSafe_DEPRECATED
from .destructiveCommandWarning import getDestructiveCommandWarning
from .modeValidation import checkPermissionMode
from .pathValidation import checkPathConstraints
from .readOnlyValidation import checkReadOnlyConstraints
from .sedValidation import checkSedConstraints


BINARY_HIJACK_VARS = {"PATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"}
MAX_SUBCOMMANDS_FOR_SECURITY_CHECK = 50
MAX_SUGGESTED_RULES_FOR_COMPOUND = 5

_SPECULATIVE_CHECKS: dict[str, Any] = {}


def _normalize_permission_context(context: ToolUseContext | dict[str, Any] | None) -> dict[str, Any]:
    if context is None:
        return {}
    if isinstance(context, dict):
        return dict(context)
    app_state = getattr(context, "app_state", None)
    permission_context = getattr(app_state, "tool_permission_context", None)
    if isinstance(permission_context, dict):
        normalized = dict(permission_context)
        normalized.setdefault("cwd", getattr(context.options, "cwd", "."))
        return normalized
    config = getattr(app_state, "config", {}) or {}
    tool_context = config.get("toolPermissionContext", {})
    if isinstance(tool_context, dict):
        normalized = dict(tool_context)
        normalized.setdefault("cwd", getattr(context.options, "cwd", "."))
        return normalized
    return {}


def permissionRuleExtractPrefix(permission_rule: str) -> str | None:
    return permission_rule[:-2] if permission_rule.endswith(":*") else None


"""
通配符匹配：
*匹配任意
？匹配一个字符
[abc]匹配三者其中一个
"""
def matchWildcardPattern(pattern: str, command: str) -> bool:
    return fnmatch.fnmatchcase(command, pattern)


def bashPermissionRule(permissionRule: str) -> dict[str, str]:
    prefix = permissionRuleExtractPrefix(permissionRule)
    if prefix is not None:
        return {"type": "prefix", "prefix": prefix}
    if "*" in permissionRule or "?" in permissionRule:
        return {"type": "wildcard", "pattern": permissionRule}
    return {"type": "exact", "command": permissionRule}


def stripAllLeadingEnvVars(command: str, safe_env_vars: set[str] | None = None) -> str:
    safe_set = SAFE_ENV_VARS if safe_env_vars is None else safe_env_vars
    return strip_all_leading_env_vars(command, safe_set)


def stripSafeWrappers(command: str) -> str:
    return strip_safe_wrappers(command)


def getSimpleCommandPrefix(command: str) -> str | None:
    stripped = strip_safe_wrappers(command).strip()
    tokens = stripped.split()
    if len(tokens) < 2:
        return None
    subcommand = tokens[1]
    if not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", subcommand):
        return None
    return " ".join(tokens[:2])


def getFirstWordPrefix(command: str) -> str | None:
    stripped = strip_safe_wrappers(command).strip()
    first = stripped.split(maxsplit=1)[0] if stripped else ""
    if not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", first):
        return None
    if first in {"sh", "bash", "zsh", "fish", "cmd", "powershell", "pwsh", "env", "xargs", "sudo", "doas"}:
        return None
    return first


def _suggestion_for_pattern(pattern: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "addRules",
            "rules": [pattern],
            "behavior": "allow",
            "destination": "localSettings",
        }
    ]


def _suggestion_for_exact_command(command: str) -> list[dict[str, Any]]:
    prefix = getSimpleCommandPrefix(command) or getFirstWordPrefix(command)
    if prefix:
        return _suggestion_for_pattern(f"{prefix}:*")
    return _suggestion_for_pattern(command)


def _command_candidates(command: str) -> list[str]:
    candidates = [command.strip()]
    seen = set(candidates)
    start_index = 0
    while start_index < len(candidates):
        end_index = len(candidates)
        for candidate in candidates[start_index:end_index]:
            for derived in (
                stripAllLeadingEnvVars(candidate, SAFE_ENV_VARS),
                stripSafeWrappers(candidate),
            ):
                derived = derived.strip()
                if derived and derived not in seen:
                    candidates.append(derived)
                    seen.add(derived)
        start_index = end_index
    return candidates


def _match_rules(command: str, rules: list[str]) -> str | None:
    candidates = _command_candidates(command)
    for rule_text in rules:
        rule = bashPermissionRule(rule_text)
        for candidate in candidates:
            if rule["type"] == "exact" and candidate == rule["command"]:
                return rule_text
            if rule["type"] == "prefix" and (
                candidate == rule["prefix"] or candidate.startswith(rule["prefix"] + " ")
            ):
                return rule_text
            if rule["type"] == "wildcard" and matchWildcardPattern(rule["pattern"], candidate):
                return rule_text
    return None


def isNormalizedGitCommand(command: str) -> bool:
    stripped = stripSafeWrappers(command).strip()
    return stripped == "git" or stripped.startswith("git ")


def isNormalizedCdCommand(command: str) -> bool:
    stripped = stripSafeWrappers(command).strip()
    return stripped == "cd" or stripped.startswith("cd ") or stripped.startswith("pushd ") or stripped.startswith("popd ")


def commandHasAnyCd(command: str) -> bool:
    return any(isNormalizedCdCommand(subcmd) for subcmd in split_command_deprecated(command))


def bashToolCheckExactMatchPermission(
    input_data: dict[str, Any],
    toolPermissionContext: dict[str, Any] | None,
) -> dict[str, Any]:
    context = dict(toolPermissionContext or {})
    command = str(input_data.get("command", ""))
    deny_match = _match_rules(command, list(context.get("deny_rules", [])))
    if deny_match:
        return {
            "behavior": "deny",
            "message": f"Permission to use Bash with command {command} has been denied.",
            "decisionReason": {"type": "rule", "rule": deny_match, "behavior": "deny"},
        }
    allow_match = _match_rules(command, list(context.get("allow_rules", [])))
    if allow_match:
        return {
            "behavior": "allow",
            "updatedInput": input_data,
            "decisionReason": {"type": "rule", "rule": allow_match, "behavior": "allow"},
        }
    return {"behavior": "passthrough", "message": "No exact permission rule matched"}


def bashToolCheckPermission(
    input_data: dict[str, Any],
    toolPermissionContext: dict[str, Any] | None,
    compoundCommandHasCd: bool = False,
    _ast_command: Any = None,
) -> dict[str, Any]:
    command = str(input_data.get("command", ""))
    context = dict(toolPermissionContext or {})
    exact_match = bashToolCheckExactMatchPermission(input_data, context)
    if exact_match.get("behavior") in {"allow", "deny"}:
        return exact_match
    mode_result = checkPermissionMode(input_data, context)
    if mode_result.get("behavior") == "allow":
        return mode_result
    read_only_result = checkReadOnlyConstraints(input_data, compoundCommandHasCd)
    if read_only_result.get("behavior") == "allow":
        return read_only_result
    path_result = checkPathConstraints(
        input_data,
        str(context.get("cwd") or context.get("working_directory") or context.get("default_cwd") or "."),
        context,
        compoundCommandHasCd,
    )
    if path_result.get("behavior") in {"ask", "deny"}:
        return path_result
    sed_result = checkSedConstraints(input_data, context)
    if sed_result.get("behavior") == "ask":
        sed_result.setdefault("suggestions", _suggestion_for_exact_command(command))
        return sed_result
    security_result = bashCommandIsSafe_DEPRECATED(command)
    if security_result.get("behavior") == "ask":
        return {
            "behavior": "ask",
            "message": str(security_result.get("message") or "Command requires approval"),
            "decisionReason": {"type": "other", "reason": security_result.get("message")},
            "suggestions": [],
        }
    warning = getDestructiveCommandWarning(command)
    if warning:
        return {
            "behavior": "ask",
            "message": warning,
            "decisionReason": {"type": "other", "reason": warning},
            "suggestions": _suggestion_for_exact_command(command),
        }
    return {
        "behavior": "ask",
        "message": "Command requires approval.",
        "decisionReason": {"type": "other", "reason": "Command is not covered by auto-allow rules"},
        "suggestions": _suggestion_for_exact_command(command),
    }


async def checkCommandAndSuggestRules(
    input_data: dict[str, Any],
    toolPermissionContext: dict[str, Any] | None,
    _commandSubcommandPrefix: Any = None,
    compoundCommandHasCd: bool = False,
    _hasAstSubcommands: bool = False,
) -> dict[str, Any]:
    return bashToolCheckPermission(input_data, toolPermissionContext, compoundCommandHasCd)


async def bashToolHasPermission(
    input_data: dict[str, Any],
    context: ToolUseContext | dict[str, Any] | None = None,
) -> dict[str, Any]:
    tool_context = _normalize_permission_context(context)
    if context is not None and not isinstance(context, dict):
        tool_context.setdefault("cwd", getattr(context.options, "cwd", "."))
    compound_command_has_cd = commandHasAnyCd(str(input_data.get("command", "")))
    if len(split_command_deprecated(str(input_data.get("command", "")))) > MAX_SUBCOMMANDS_FOR_SECURITY_CHECK:
        return {
            "behavior": "ask",
            "message": "Command is too complex to safety-check automatically.",
            "decisionReason": {"type": "other", "reason": "Too many subcommands"},
        }
    return bashToolCheckPermission(input_data, tool_context, compound_command_has_cd)


def clearSpeculativeChecks() -> None:
    _SPECULATIVE_CHECKS.clear()


def startSpeculativeClassifierCheck(command: str, value: Any | None = None) -> str:
    key = command.strip()
    _SPECULATIVE_CHECKS[key] = value
    return key


def peekSpeculativeClassifierCheck(command: str) -> Any:
    return _SPECULATIVE_CHECKS.get(command.strip())


def consumeSpeculativeClassifierCheck(command: str) -> Any:
    return _SPECULATIVE_CHECKS.pop(command.strip(), None)


async def executeAsyncClassifierCheck(command: str, *_args: Any, **_kwargs: Any) -> Any:
    return peekSpeculativeClassifierCheck(command)


async def awaitClassifierAutoApproval(command: str, *_args: Any, **_kwargs: Any) -> Any:
    return consumeSpeculativeClassifierCheck(command)


__all__ = [
    "BINARY_HIJACK_VARS",
    "MAX_SUBCOMMANDS_FOR_SECURITY_CHECK",
    "MAX_SUGGESTED_RULES_FOR_COMPOUND",
    "awaitClassifierAutoApproval",
    "bashPermissionRule",
    "bashToolCheckExactMatchPermission",
    "bashToolCheckPermission",
    "bashToolHasPermission",
    "checkCommandAndSuggestRules",
    "clearSpeculativeChecks",
    "commandHasAnyCd",
    "consumeSpeculativeClassifierCheck",
    "executeAsyncClassifierCheck",
    "getFirstWordPrefix",
    "getSimpleCommandPrefix",
    "isNormalizedCdCommand",
    "isNormalizedGitCommand",
    "matchWildcardPattern",
    "peekSpeculativeClassifierCheck",
    "permissionRuleExtractPrefix",
    "startSpeculativeClassifierCheck",
    "stripAllLeadingEnvVars",
    "stripSafeWrappers",
    "stripWrappersFromArgv",
]


stripWrappersFromArgv = strip_wrappers_from_argv
