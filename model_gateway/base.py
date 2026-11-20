"""适配器基类 —— 封装共享的 HTTP/SSE 引擎。

自研设计:把"网络传输 + SSE 帧切分"这种脏活放基类,
把"协议差异"(请求格式、事件解析)留给三个子类各自定义。

基类不认识任何具体协议,只认识统一的 Message / StreamEvent。
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import AsyncIterator

try:
    import aiohttp
except ImportError:
    aiohttp = None

from shared import ErrorCodes, ProtocolError

from .config import ModelConfig
from .types import Message, StreamEvent, ToolSpec


class BaseModelAdapter(ABC):
    protocol: str = "base"

    def __init__(self, config: ModelConfig):
        if aiohttp is None:
            raise RuntimeError("请先安装 aiohttp: pip install aiohttp")
        self.config = config

    # ---------- 子类必须实现 ----------
    @abstractmethod
    def build_request(self, messages: list[Message], tools: list[ToolSpec] | None,
                      stream: bool) -> tuple[str, dict, dict]:
        """返回 (url, headers, json_body)。"""
        ...

    @abstractmethod
    def parse_sse_data(self, data: str, state: dict) -> list[StreamEvent]:
        """解析一帧 SSE 的 data 字段(已去掉 'data:' 前缀),返回零或多个统一事件。

        state 是本次请求的可变字典,用于跨帧累积(如 tool 参数的增量 JSON)。
        """
        ...

    # ---------- 可选覆盖 ----------
    def parse_nonstream(self, payload: dict) -> list[StreamEvent]:
        """解析非流式响应。默认把各协议都尝试提取文本。"""
        return []

    # ---------- 共享引擎 ----------
    async def chat_stream(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> AsyncIterator[StreamEvent]:
        url, headers, body = self.build_request(messages, tools, stream=True)
        timeout = aiohttp.ClientTimeout(total=self.config.timeout)
        state: dict = {}
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, headers=headers, json=body) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        raise ProtocolError(
                            ErrorCodes.MODEL_API_ERROR,
                            f"[{self.protocol}] HTTP {resp.status}: {text[:400]}",
                        )
                    async for raw in resp.content:
                        line = raw.decode("utf-8", "replace").strip()
                        if not line:
                            continue
                        # 支持 "data: xxx" 与 "event: xxx\ndata: xxx" 两种 SSE
                        if line.startswith("event:"):
                            state["_event"] = line[6:].strip()
                            continue
                        if line.startswith("data:"):
                            data = line[5:].strip()
                        else:
                            continue
                        if data in ("[DONE]", "DONE"):
                            yield StreamEvent(type="done")
                            continue
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        # 把 event 名塞进 chunk,方便子类区分事件类型(Anthropic 需要)
                        if "_event" in state:
                            chunk["_event"] = state.pop("_event")
                        for event in self.parse_sse_data(data, state) or self._parse_chunk(chunk, state):
                            yield event
        except aiohttp.ClientError as exc:
            raise ProtocolError(ErrorCodes.MODEL_API_ERROR, f"[{self.protocol}] 网络错误: {exc}") from exc

    def _parse_chunk(self, chunk: dict, state: dict) -> list[StreamEvent]:
        """兜底:子类若只实现了按 data 字符串解析,这里给个空实现。"""
        return []

    async def chat(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> dict:
        """非流式调用。默认走流式引擎收集,拼成统一的 assistant 消息。"""
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: list[dict] = []
        usage: dict | None = None
        async for event in self.chat_stream(messages, tools):
            if event.type == "content":
                content_parts.append(event.text)
            elif event.type == "reasoning":
                reasoning_parts.append(event.text)
            elif event.type == "tool_call" and event.tool_call:
                tool_calls.append({
                    "id": event.tool_call.id,
                    "name": event.tool_call.name,
                    "arguments": event.tool_call.arguments,
                })
            elif event.type == "done" and event.usage:
                usage = event.usage
        msg: dict[str, object] = {"role": "assistant", "content": "".join(content_parts)}
        if reasoning_parts:
            msg["reasoning_content"] = "".join(reasoning_parts)
        if tool_calls:
            msg["tool_calls"] = tool_calls
        out: dict[str, object] = {"choices": [{"message": msg, "finish_reason": "tool_calls" if tool_calls else "stop"}]}
        if usage:
            out["usage"] = usage
        return out
