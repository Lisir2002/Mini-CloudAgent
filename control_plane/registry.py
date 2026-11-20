"""节点注册表 + 配对码认证。

管理所有在线的节点Agent,记录它们的 WebSocket 连接、能力、会话数。
任务路由从这里挑一个可用节点。
"""

from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class NodeInfo:
    node_id: str
    user_id: str
    ws: Any
    label: str = ""
    token: str = ""
    sessions: int = 0
    capabilities: dict = field(default_factory=dict)
    last_seen: float = field(default_factory=time.time)
    busy: bool = False


class NodeRegistry:
    def __init__(self, pair_codes: dict[str, str], token_ttl: int = 0):
        self.pair_codes = dict(pair_codes)     # code -> user_id
        self.token_ttl = token_ttl
        self.nodes: dict[str, NodeInfo] = {}            # node_id -> NodeInfo
        self.tokens: dict[str, tuple[str, float]] = {}   # token -> (node_id, issued_at)
        self._lock = asyncio.Lock()

    def resolve_pair(self, pair_code: str) -> str | None:
        """配对码 -> user_id。配对码用掉后即作废(一次性)。"""
        uid = self.pair_codes.pop(pair_code, None)
        return uid

    async def register(self, user_id: str, ws: Any, label: str = "", token: str = "") -> NodeInfo:
        """注册节点。带 token 走恢复流程,否则新建。"""
        async with self._lock:
            node_id = None
            if token and token in self.tokens:
                node_id, issued_at = self.tokens[token]
                # 校验 token 是否过期
                if self.token_ttl > 0 and time.time() - issued_at > self.token_ttl:
                    self.tokens.pop(token, None)
                    node_id = None
            if node_id is None:
                node_id = "node_" + secrets.token_hex(6)
                token = secrets.token_urlsafe(24)
                self.tokens[token] = (node_id, time.time())

            info = NodeInfo(
                node_id=node_id,
                user_id=user_id,
                ws=ws,
                label=label,
                token=token,
            )
            self.nodes[node_id] = info
            return info

    async def unregister(self, node_id: str) -> None:
        async with self._lock:
            self.nodes.pop(node_id, None)

    def heartbeat(self, node_id: str, sessions: int, platform: str = "") -> None:
        info = self.nodes.get(node_id)
        if info:
            info.sessions = sessions
            info.last_seen = time.time()
            info.capabilities["platform"] = platform

    def pick_node(self, user_id: str) -> NodeInfo | None:
        """为用户挑一个在线且不太忙的节点。"""
        candidates = [
            n for n in self.nodes.values()
            if n.user_id == user_id and not n.busy
        ]
        if not candidates:
            return None
        # 选会话数最少的
        return min(candidates, key=lambda n: n.sessions)

    def list_nodes(self, user_id: str) -> list[dict]:
        return [
            {
                "node_id": n.node_id,
                "label": n.label,
                "sessions": n.sessions,
                "online": True,
                "last_seen": n.last_seen,
                "capabilities": n.capabilities,
            }
            for n in self.nodes.values() if n.user_id == user_id
        ]
