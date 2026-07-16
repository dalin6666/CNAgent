from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path

from agent_runtime import AgentRuntime, SessionState
from agent_runtime.application import (
    WEB_SAFE_TOOL_GROUPS,
    build_runtime_from_env,
    new_session,
    prepare_next_run,
)


@dataclass
class Conversation:
    session: SessionState
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class AgentService:
    def __init__(
        self,
        *,
        workdir: str | os.PathLike[str],
        allowed_tool_groups: set[str] | None = None,
        runtime: AgentRuntime | None = None,
    ) -> None:
        self.workdir = str(Path(workdir).expanduser().resolve())
        self.allowed_tool_groups = set(allowed_tool_groups or WEB_SAFE_TOOL_GROUPS)
        self._runtime = runtime
        self._conversations: dict[int, Conversation] = {}
        self._runtime_lock = asyncio.Lock()

    async def reply(self, *, user_id: int, message: str) -> str:
        prompt = message.strip()
        if not prompt:
            return ""

        conversation = self._conversation_for(user_id)
        async with conversation.lock:
            runtime = await self._get_runtime()
            prepare_next_run(conversation.session)
            chunks: list[str] = []
            async for event in runtime.stream(prompt, session=conversation.session):
                if event.kind == "text_delta":
                    chunks.append(event.text)
            return "".join(chunks).strip()

    def reset(self, *, user_id: int) -> None:
        self._conversations.pop(user_id, None)

    def _conversation_for(self, user_id: int) -> Conversation:
        conversation = self._conversations.get(user_id)
        if conversation is None:
            conversation = Conversation(session=new_session(self.workdir))
            self._conversations[user_id] = conversation
        return conversation

    async def _get_runtime(self) -> AgentRuntime:
        if self._runtime is not None:
            return self._runtime

        async with self._runtime_lock:
            if self._runtime is None:
                self._runtime = build_runtime_from_env(
                    workdir=self.workdir,
                    allowed_tool_groups=self.allowed_tool_groups,
                )
            return self._runtime
