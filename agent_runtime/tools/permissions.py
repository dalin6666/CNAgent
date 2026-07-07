from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..errors import ToolPermissionError


@dataclass(slots=True)
class PermissionManager:
    allowed_groups: set[str] = field(default_factory=set)  # 允许的Tool组
    allowed_tools: set[str] = field(default_factory=set)   # 允许的单个Tool集合
    blocked_tools: set[str] = field(default_factory=set)
    blocked_groups: set[str] = field(default_factory=set)
    allow_all: bool = False

    @staticmethod
    def _normalize_name(value: str) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("Permission target must be a non-empty string.")
        return normalized

    # 添加允许的组
    def grant_group(self, permission_group: str) -> None:
        self.allowed_groups.add(self._normalize_name(permission_group))

    # 取消权限组，discard:若permission_group不存在也不会报错
    def revoke_group(self, permission_group: str) -> None:
        self.allowed_groups.discard(self._normalize_name(permission_group))

    # 添加到禁止组
    def block_group(self, permission_group: str) -> None:
        self.blocked_groups.add(self._normalize_name(permission_group))

    # 从禁止组中移除
    def unblock_group(self, permission_group: str) -> None:
        self.blocked_groups.discard(self._normalize_name(permission_group))

    def grant_tool(self, tool_name: str) -> None:
        self.allowed_tools.add(self._normalize_name(tool_name))

    def revoke_tool(self, tool_name: str) -> None:
        self.allowed_tools.discard(self._normalize_name(tool_name))

    def block_tool(self, tool_name: str) -> None:
        self.blocked_tools.add(self._normalize_name(tool_name))

    def unblock_tool(self, tool_name: str) -> None:
        self.blocked_tools.discard(self._normalize_name(tool_name))

    def is_allowed(self, tool_name: str, permission_group: str) -> bool:
        normalized_tool = self._normalize_name(tool_name)
        normalized_group = self._normalize_name(permission_group)
        if normalized_tool in self.blocked_tools:
            return False
        if normalized_group in self.blocked_groups:
            return False
        if normalized_tool in self.allowed_tools:
            return True
        if self.allow_all:
            return True
        return normalized_group in self.allowed_groups

    # 返回更详细的判断原因
    def explain(self, tool_name: str, permission_group: str) -> dict[str, Any]:
        normalized_tool = self._normalize_name(tool_name)
        normalized_group = self._normalize_name(permission_group)
        if normalized_tool in self.blocked_tools:
            return {
                "allowed": False,
                "reason": "tool_blocked",
                "tool_name": normalized_tool,
                "permission_group": normalized_group,
            }
        if normalized_group in self.blocked_groups:
            return {
                "allowed": False,
                "reason": "group_blocked",
                "tool_name": normalized_tool,
                "permission_group": normalized_group,
            }
        if normalized_tool in self.allowed_tools:
            return {
                "allowed": True,
                "reason": "tool_allowed",
                "tool_name": normalized_tool,
                "permission_group": normalized_group,
            }
        if self.allow_all:
            return {
                "allowed": True,
                "reason": "allow_all",
                "tool_name": normalized_tool,
                "permission_group": normalized_group,
            }
        if normalized_group in self.allowed_groups:
            return {
                "allowed": True,
                "reason": "group_allowed",
                "tool_name": normalized_tool,
                "permission_group": normalized_group,
            }
        return {
            "allowed": False,
            "reason": "group_not_allowed",
            "tool_name": normalized_tool,
            "permission_group": normalized_group,
        }

    # 导出当前的权限配置
    def snapshot(self) -> dict[str, Any]:
        return {
            "allow_all": self.allow_all,
            "allowed_groups": sorted(self.allowed_groups),
            "allowed_tools": sorted(self.allowed_tools),
            "blocked_groups": sorted(self.blocked_groups),
            "blocked_tools": sorted(self.blocked_tools),
        }

    # 不允许就抛出异常
    def ensure_allowed(self, tool_name: str, permission_group: str) -> None:
        decision = self.explain(tool_name, permission_group)
        if decision["allowed"]:
            return
        reason = decision["reason"]
        if reason == "tool_blocked":
            raise ToolPermissionError(f"Tool blocked by policy: {tool_name}")
        if reason == "group_blocked":
            raise ToolPermissionError(
                f"Tool group '{permission_group}' is blocked for tool '{tool_name}'."
            )
        if reason == "group_not_allowed":
            raise ToolPermissionError(
                f"Tool group '{permission_group}' is not allowed for tool '{tool_name}'."
            )
