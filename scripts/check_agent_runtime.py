from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.agent_service import AgentService


async def run() -> int:
    root = ROOT
    load_dotenv(root / ".env")
    service = AgentService(workdir=root, allowed_tool_groups={"read", "lookup"})
    answer = await service.reply(user_id=1, message="帮我用一句话介绍 AI Agent")
    print(answer[:1000] or "<empty answer>")
    return 0


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
