"""端到端联调:控制面 + 节点Agent + 客户端,跑通一次完整任务。

用法:
    python -m demo.e2e_test

流程:
1. 后台线程启动控制面(uvicorn,端口 8765)
2. 启动节点Agent(本地沙箱降级,无需 Docker),用配对码 DEMO2026 注册
3. 模拟 App 客户端连接控制面
4. 客户端:创建沙箱会话 -> 执行 Python 代码 -> 收流式结果 -> 读写文件 -> 关闭
5. 全部断言通过后打印成功

这是验证"大脑与手通过统一协议通信"的最小闭环。
"""

from __future__ import annotations

import asyncio
import threading
import time

import uvicorn
import websockets
from websockets.asyncio.client import connect

from control_plane import ControlConfig, create_app
from node_agent.agent import NodeAgent
from node_agent.config import AgentConfig
from node_agent.sandbox import create_sandbox
from shared import (
    Methods,
    RpcNotification,
    RpcRequest,
    RpcResponse,
    build_request,
    parse_message,
    to_json,
)

PORT = 8765
CONTROL_URL = f"ws://127.0.0.1:{PORT}"


def start_control_plane():
    config = ControlConfig(host="127.0.0.1", port=PORT)
    app = create_app(config)
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="error")


async def wait_control_ready():
    import aiohttp
    for _ in range(40):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"http://127.0.0.1:{PORT}/health", timeout=aiohttp.ClientTimeout(total=1)) as r:
                    if r.status == 200:
                        return
        except Exception:
            pass
        await asyncio.sleep(0.25)
    raise RuntimeError("控制面未能启动")


async def run_node():
    cfg = AgentConfig(
        control_url=f"{CONTROL_URL}/ws/node",
        pair_code="DEMO2026",
        label="e2e-test-node",
        sandbox_backend="local",
        workdir="/tmp/e2e_sandbox",
        token_file="/tmp/e2e_node_token",
    )
    import os
    if os.path.exists(cfg.token_file):
        os.remove(cfg.token_file)  # 确保走配对码注册
    sandbox = await create_sandbox(cfg)
    agent = NodeAgent(cfg, sandbox)
    # 只跑一次连接循环:起一个后台任务
    return asyncio.create_task(agent.start())


async def client_flow():
    """模拟 App:连控制面,创建会话,执行代码,验证流式输出。"""
    async with connect(f"{CONTROL_URL}/ws/client") as ws:
        # 1. hello
        hello = build_request("client.hello", {"user_id": "demo-user"}, rid="hello-1")
        await ws.send(to_json(hello))
        resp = parse_message(await ws.recv())
        assert isinstance(resp, RpcResponse), f"hello 响应异常: {resp}"
        print("[客户端] 握手成功")

        # 2. 等节点上线
        await asyncio.sleep(1)
        nodes_req = build_request("node.list", {}, rid="nodes-1")
        await ws.send(to_json(nodes_req))
        nodes_resp = parse_message(await ws.recv())
        nodes = nodes_resp.result.get("nodes", [])
        assert nodes, "没有节点上线"
        print(f"[客户端] 发现节点: {nodes[0]['label']}")

        # 3. 创建会话
        cr = build_request(Methods.SESSION_CREATE, {}, rid="create-1")
        await ws.send(to_json(cr))
        # 可能先收到 stream.accepted 通知,循环找响应
        sid = None
        for _ in range(5):
            msg = parse_message(await asyncio.wait_for(ws.recv(), timeout=10))
            if isinstance(msg, RpcResponse) and msg.id == "create-1":
                sid = msg.result["session_id"]
                break
        assert sid, "会话创建失败"
        print(f"[客户端] 会话创建: {sid}")

        # 4. 执行代码(带标记便于验证)
        marker = "E2E_MARKER_9527"
        ex = build_request(Methods.EXEC_RUN, {
            "session_id": sid,
            "code": f"print('{marker}'); import sys; print('to stderr', file=sys.stderr)",
            "language": "python",
        }, rid="exec-1")
        await ws.send(to_json(ex))

        collected = []
        got_final = False
        for _ in range(20):
            msg = parse_message(await asyncio.wait_for(ws.recv(), timeout=15))
            if isinstance(msg, RpcNotification) and msg.method == Methods.STREAM_OUTPUT:
                collected.append(msg.params.get("text", ""))
            elif isinstance(msg, RpcResponse) and msg.id == "exec-1":
                got_final = True
                break
        joined = "".join(collected)
        assert marker in joined, f"未收到 stdout: {collected}"
        assert "to stderr" in joined, f"未收到 stderr: {collected}"
        assert got_final, "未收到执行完成响应"
        print(f"[客户端] 收到流式输出: {joined.strip()!r}")

        # 5. 关闭会话
        cl = build_request(Methods.SESSION_CLOSE, {"session_id": sid}, rid="close-1")
        await ws.send(to_json(cl))
        for _ in range(5):
            msg = parse_message(await asyncio.wait_for(ws.recv(), timeout=10))
            if isinstance(msg, RpcResponse) and msg.id == "close-1":
                assert msg.result.get("ok")
                break
        print("[客户端] 会话已关闭")
        return True


async def main():
    print("=== 启动控制面 ===")
    t = threading.Thread(target=start_control_plane, daemon=True)
    t.start()
    await wait_control_ready()
    print(f"[控制面] 已就绪 http://127.0.0.1:{PORT}")

    print("=== 启动节点Agent ===")
    node_task = await run_node()
    await asyncio.sleep(0.5)

    print("=== 客户端联调 ===")
    ok = await client_flow()

    node_task.cancel()
    assert ok
    print("\n=== 端到端联调通过:大脑 <-> 协议 <-> 手 全链路正常 ===")


if __name__ == "__main__":
    asyncio.run(main())
