"""控制面 FastAPI 应用。

三类连接:
1. /ws/node  —— 节点Agent 主动连上来(手)
2. /ws/client —— App/客户端 连上来(大脑的用户入口)
3. /health   —— 健康检查

核心机制:请求-响应关联。
客户端发请求 -> 控制面分配一个 relay_id,转发给节点;
节点的响应/流式通知带同样的 id -> 控制面找回对应客户端连接回传。
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
except ImportError:
    FastAPI = None
    WebSocket = None
    WebSocketDisconnect = None

from shared import (
    ErrorCodes,
    Methods,
    ProtocolError,
    RpcNotification,
    RpcRequest,
    RpcResponse,
    RpcErrorResponse,
    build_error,
    build_response,
    parse_message,
    to_json,
)

from .config import ControlConfig
from .registry import NodeRegistry


class ControlPlane:
    def __init__(self, config: ControlConfig):
        self.config = config
        self.registry = NodeRegistry(config.pair_codes, config.token_ttl)

        # client_id -> WebSocket(客户端连接)
        self.clients: dict[str, WebSocket] = {}
        # client_id -> user_id
        self.client_users: dict[str, str] = {}
        # relay_id -> client_id(正在等待响应的请求)
        self.pending: dict[str, str] = {}
        self._lock = asyncio.Lock()

    # ---------------- 节点连接 ----------------
    async def handle_node(self, ws: WebSocket) -> None:
        await ws.accept()
        node_id: str | None = None
        try:
            while True:
                raw = await ws.receive_text()
                msg = parse_message(raw)
                if isinstance(msg, RpcRequest):
                    # 只处理 node.register 和 node.heartbeat;其余是节点回传的响应
                    if msg.method == Methods.NODE_REGISTER:
                        node_id = await self._on_node_register(ws, msg)
                    elif msg.method == Methods.NODE_HEARTBEAT:
                        self.registry.heartbeat(
                            msg.params.get("node_id") or node_id,
                            msg.params.get("sessions", 0),
                            msg.params.get("platform", ""),
                        )
                    else:
                        # 节点把 execute 的 stream.* 通知或响应发回来了
                        await self._relay_from_node(msg)
                elif isinstance(msg, RpcNotification):
                    await self._relay_from_node(msg)
                elif isinstance(msg, (RpcResponse, RpcErrorResponse)):
                    await self._relay_from_node(msg)
        except WebSocketDisconnect:
            pass
        except ProtocolError as exc:
            try:
                await ws.send_text(to_json(build_error(None, exc.code, exc.message)))
            except Exception:
                pass
        finally:
            if node_id:
                await self.registry.unregister(node_id)

    async def _on_node_register(self, ws: WebSocket, req: RpcRequest) -> str:
        p = req.params
        token = p.get("token", "")
        if token:
            # 已有 token:恢复/新建节点身份
            info = await self.registry.register("", ws, p.get("label", ""), token)
        else:
            pair_code = p.get("pair_code", "")
            uid = self.registry.resolve_pair(pair_code)
            if not uid:
                raise ProtocolError(ErrorCodes.PAIR_CODE_INVALID)
            info = await self.registry.register(uid, ws, p.get("label", ""))
        await ws.send_text(to_json(build_response(req.id, {
            "node_id": info.node_id,
            "token": info.token,
        })))
        return info.node_id

    async def _relay_from_node(self, msg) -> None:
        """把节点发来的消息回传给等待中的客户端。

        转发时保留了客户端的原始 request_id,所以这里:
        - 响应:按 msg.id(= 原始 id)在 pending 找客户端,发完清理映射
        - 通知:按 params.request_id 找客户端,不清理(一个请求有多帧)
        """
        rid = getattr(msg, "id", None)
        params = getattr(msg, "params", {}) or {}

        # 响应
        if rid and rid in self.pending:
            cid = self.pending.pop(rid)
            client = self.clients.get(cid)
            if client:
                try:
                    await client.send_text(to_json(msg))
                except Exception:
                    pass
            return

        # 流式通知(无 id):用 params 里携带的原始 request_id
        assoc = params.get("request_id") or params.get("task_id")
        if assoc and assoc in self.pending:
            cid = self.pending[assoc]
            client = self.clients.get(cid)
            if client:
                try:
                    await client.send_text(to_json(msg))
                except Exception:
                    pass

    # ---------------- 客户端连接 ----------------
    async def handle_client(self, ws: WebSocket) -> None:
        await ws.accept()
        cid = None
        try:
            # 首帧必须是 hello:{user_id}
            raw = await ws.receive_text()
            hello = parse_message(raw)
            if not isinstance(hello, RpcRequest) or hello.method != "client.hello":
                await ws.send_text(to_json(build_error(None, ErrorCodes.INVALID_REQUEST, "先发 client.hello")))
                return
            uid = hello.params.get("user_id", "demo-user")
            cid = hello.id
            self.clients[cid] = ws
            self.client_users[cid] = uid
            await ws.send_text(to_json(build_response(cid, {"ok": True, "client_id": cid})))

            while True:
                raw = await ws.receive_text()
                msg = parse_message(raw)
                if isinstance(msg, RpcRequest):
                    await self._on_client_request(cid, uid, ws, msg)
        except WebSocketDisconnect:
            pass
        except ProtocolError as exc:
            try:
                await ws.send_text(to_json(build_error(None, exc.code, exc.message)))
            except Exception:
                pass
        finally:
            if cid:
                self.clients.pop(cid, None)
                self.client_users.pop(cid, None)

    async def _on_client_request(self, cid: str, uid: str, ws: WebSocket, req: RpcRequest) -> None:
        # 节点列表查询,控制面直接答
        if req.method == "node.list":
            await ws.send_text(to_json(build_response(req.id, {"nodes": self.registry.list_nodes(uid)})))
            return

        # 其余方法转发给节点
        node = self.registry.pick_node(uid)
        if not node:
            await ws.send_text(to_json(build_error(req.id, ErrorCodes.NODE_NOT_FOUND)))
            return

        # 保留客户端原始 id 转发,这样节点回的响应 id 天然能对上客户端等待。
        # 同时把原始 id 作为 task_id 塞进 params,节点发流式通知时会带回,
        # 控制面据此把通知路由给正确的客户端。
        self.pending[req.id] = cid
        forwarded = RpcRequest(
            id=req.id,
            method=req.method,
            params={**req.params, "task_id": req.id},
        )
        try:
            await node.ws.send_text(to_json(forwarded))
        except Exception:
            self.pending.pop(req.id, None)
            await ws.send_text(to_json(build_error(req.id, ErrorCodes.NODE_NOT_FOUND, "节点连接已断开")))


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


def create_app(config: ControlConfig | None = None) -> FastAPI:
    if FastAPI is None:
        raise RuntimeError("请先安装 fastapi: pip install fastapi uvicorn")
    config = config or ControlConfig()
    cp = ControlPlane(config)

    app = FastAPI(title="Agent Runtime 控制面", lifespan=lifespan)
    app.state.control = cp

    @app.get("/health")
    async def health():
        return {"status": "ok", "nodes": len(cp.registry.nodes), "clients": len(cp.clients)}

    @app.get("/nodes")
    async def nodes(user_id: str = "demo-user"):
        return {"nodes": cp.registry.list_nodes(user_id)}

    @app.websocket("/ws/node")
    async def ws_node(websocket: WebSocket):
        await cp.handle_node(websocket)

    @app.websocket("/ws/client")
    async def ws_client(websocket: WebSocket):
        await cp.handle_client(websocket)

    return app
