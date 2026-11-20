"""节点Agent主程序:安装到用户服务器后常驻运行。

职责:
1. 主动外连控制面(反向长连接,穿透 NAT)
2. 首次用配对码注册,换取长期 token 并持久化
3. 心跳保活 + 上报负载
4. 接收控制面下发的任务,交给沙箱执行,流式回传结果

传输层用的是 websockets 库。协议层(shared)完全不感知传输,
所以后期换成手机本地的传输方式时,这里可整体替换。
"""

from __future__ import annotations

import asyncio
import json
import platform
from typing import Any

try:
    import websockets
    from websockets.asyncio.client import connect
except ImportError:
    websockets = None
    connect = None

from shared import (
    ErrorCodes,
    Methods,
    ProtocolError,
    RpcNotification,
    RpcRequest,
    build_error,
    build_notification,
    build_response,
    parse_message,
    to_json,
)

from .config import AgentConfig
from .executors import normalize_language
from .sandbox import BaseSandbox, create_sandbox


class NodeAgent:
    def __init__(self, config: AgentConfig, sandbox: BaseSandbox):
        self.config = config
        self.sandbox = sandbox
        self.node_id: str | None = None
        self.ws = None
        self._running_tasks: dict[str, asyncio.Task] = {}

    async def start(self) -> None:
        if connect is None:
            raise RuntimeError("请先安装 websockets: pip install websockets")
        url = self.config.control_url
        print(f"[节点] 连接控制面 {url} ...")
        async for ws in connect(url, open_timeout=10, ping_interval=20, ping_timeout=20):
            self.ws = ws
            try:
                # 上线:有 token 用 token 恢复身份,否则用配对码注册
                await self._hello()
                consumer = asyncio.create_task(self._receive_loop(ws))
                heartbeat = asyncio.create_task(self._heartbeat_loop(ws))
                done, pending = await asyncio.wait(
                    {consumer, heartbeat}, return_when=asyncio.FIRST_COMPLETED
                )
                for t in pending:
                    t.cancel()
            except websockets.ConnectionClosed:
                pass
            finally:
                self.ws = None
            print("[节点] 连接断开,3 秒后重连...")
            await asyncio.sleep(3)

    async def _hello(self) -> None:
        token = self.config.load_token()
        if token:
            req = self._req(Methods.NODE_REGISTER, {"token": token, "label": self.config.label})
        else:
            if not self.config.pair_code:
                raise RuntimeError("既没有 node_token 也没有 pair_code,无法注册")
            req = self._req(Methods.NODE_REGISTER, {
                "pair_code": self.config.pair_code, "label": self.config.label
            })
        await self.ws.send(to_json(req))
        # 注册响应会在 receive_loop 里处理,这里不阻塞

    async def _receive_loop(self, ws) -> None:
        async for raw in ws:
            try:
                msg = parse_message(raw)
            except ProtocolError as exc:
                await ws.send(to_json(build_error(None, exc.code, exc.message)))
                continue

            if isinstance(msg, RpcRequest):
                asyncio.create_task(self._handle_request(ws, msg))
            # 响应(如注册结果)由 _handle_response 处理
            elif hasattr(msg, "result") or hasattr(msg, "error"):
                self._handle_response(msg)

    def _handle_response(self, msg) -> None:
        # 注册响应:msg.id 对应 node.register 的请求 id
        result = getattr(msg, "result", None)
        error = getattr(msg, "error", None)
        if error:
            print(f"[节点] 注册失败: {error}")
            return
        if isinstance(result, dict) and "node_id" in result:
            self.node_id = result["node_id"]
            token = result.get("token")
            if token:
                self.config.save_token(token)
            print(f"[节点] 注册成功,node_id={self.node_id}")

    async def _handle_request(self, ws, req: RpcRequest) -> None:
        try:
            result = await self._dispatch(ws, req)
            await ws.send(to_json(build_response(req.id, result)))
        except ProtocolError as exc:
            await ws.send(to_json(build_error(req.id, exc.code, exc.message)))
        except Exception as exc:
            await ws.send(to_json(build_error(req.id, ErrorCodes.INTERNAL_ERROR, str(exc))))

    async def _dispatch(self, ws, req: RpcRequest) -> Any:
        m = req.method
        p = req.params

        if m == Methods.SESSION_CREATE:
            if len(self.sandbox.sessions) >= self.config.max_sessions:
                raise ProtocolError(ErrorCodes.SESSION_LIMIT)
            s = await self.sandbox.create_session(p.get("metadata"))
            return {"session_id": s.session_id, "backend": self.sandbox.backend_name}

        if m == Methods.SESSION_CLOSE:
            await self.sandbox.close_session(p["session_id"])
            return {"ok": True}

        if m == Methods.SESSION_LIST:
            return {"sessions": list(self.sandbox.sessions.keys())}

        if m == Methods.EXEC_RUN:
            sid = p["session_id"]
            code = p["code"]
            lang = normalize_language(p.get("language", "python"))
            timeout = p.get("timeout", self.config.exec_timeout)
            # 边执行边推送 stream.* 通知
            async for frame in self.sandbox.run(sid, code, lang, timeout):
                await ws.send(to_json(build_notification(Methods.STREAM_OUTPUT, {
                    "session_id": sid,
                    "task_id": p.get("task_id"),
                    **frame,
                })))
            await ws.send(to_json(build_notification(Methods.STREAM_EVENT, {
                "session_id": sid, "task_id": p.get("task_id"), "event": "done"
            })))
            return {"ok": True}

        if m == Methods.EXEC_INTERRUPT:
            ok = await self.sandbox.interrupt(p["session_id"])
            return {"ok": ok}

        if m == Methods.FILE_READ:
            return {"content": await self.sandbox.read_file(p["session_id"], p["path"])}

        if m == Methods.FILE_WRITE:
            await self.sandbox.write_file(p["session_id"], p["path"], p["content"])
            return {"ok": True}

        if m == Methods.FILE_LIST:
            return {"files": await self.sandbox.list_files(p["session_id"], p.get("path", "."))}

        if m == Methods.CAPABILITIES_GET:
            return await self.sandbox.capabilities()

        raise ProtocolError(ErrorCodes.METHOD_NOT_FOUND, f"未知方法: {m}")

    async def _heartbeat_loop(self, ws) -> None:
        while True:
            await asyncio.sleep(15)
            req = self._req(Methods.NODE_HEARTBEAT, {
                "node_id": self.node_id,
                "sessions": len(self.sandbox.sessions),
                "platform": platform.platform(),
            })
            await ws.send(to_json(req))

    def _req(self, method: str, params: dict) -> RpcRequest:
        from shared import build_request
        return build_request(method, params)
