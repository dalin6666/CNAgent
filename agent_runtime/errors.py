from __future__ import annotations


class AgentRuntimeError(Exception):
    pass


class PromptTooLongError(AgentRuntimeError):
    pass


class ProviderExecutionError(AgentRuntimeError):
    pass


class ProviderUnavailableError(AgentRuntimeError):
    pass


class ToolPermissionError(AgentRuntimeError):
    pass


class PathOutsideWorkspaceError(AgentRuntimeError, ValueError):
    pass


class ToolExecutionError(AgentRuntimeError):
    pass


class UserInterruptedError(AgentRuntimeError):
    pass
