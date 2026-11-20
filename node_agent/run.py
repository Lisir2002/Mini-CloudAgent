"""节点Agent启动入口。

用法:
    python -m node_agent.run

配置全部走环境变量 / .node_token 文件,方便 GitHub 一键脚本分发。
"""

from __future__ import annotations

import asyncio

from .agent import NodeAgent
from .config import AgentConfig
from .sandbox import create_sandbox


async def main() -> None:
    config = AgentConfig()
    sandbox = await create_sandbox(config)
    print(f"[节点] 沙箱后端: {sandbox.backend_name}, 标签: {config.label}")
    agent = NodeAgent(config, sandbox)
    await agent.start()


if __name__ == "__main__":
    asyncio.run(main())
