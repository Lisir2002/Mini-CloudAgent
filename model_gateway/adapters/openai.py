"""OpenAI Chat Completions 协议适配器。

覆盖:OpenAI 官方、三家运营商 MaaS、DeepSeek、通义、Moonshot 及绝大多数兼容服务。
"""

from __future__ import annotations

import json
from typing import AsyncIterator

from ..base import BaseModelAdapter
from ..types import Message, StreamEvent, ToolCall, ToolSpec


class OpenAIAdapter(BaseModelAdapter):
    protocol = "openai"

    def build_request(self, messages: list[Message], tools: list[ToolSpec] | None,
                      stream: bool) -> tuple[str, dict, dict]:
        base = self.config.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            url = base
        else:
            url = f"{base}/chat/completions"

        body: dict = {
            "model": self.config.model,
            "messages": self._serialize_messages(messages),
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stream": stream,
        }
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
        body.update(self.config.extra_body)

        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        return url, headers, body

    def _serialize_messages(self, messages: list[Message]) -> list[dict]:
        out: list[dict] = []
        for m in messages:
            d: dict = {"role": m.role, "content": m.content}
            if m.role == "tool":
                d["tool_call_id"] = m.tool_call_id
                if m.name:
                    d["name"] = m.name
            if m.tool_calls:
                d["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in m.tool_calls
                ]
            out.append(d)
        return out

    def parse_sse_data(self, data: str, state: dict) -> list[StreamEvent]:
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            return []
        return self._parse_chunk(chunk, state)

    def _parse_chunk(self, chunk: dict, state: dict) -> list[StreamEvent]:
        events: list[StreamEvent] = []
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}

            if delta.get("content"):
                events.append(StreamEvent(type="content", text=delta["content"]))
            # 部分兼容端点(如部分国产模型)用 reasoning_content
            if delta.get("reasoning_content"):
                events.append(StreamEvent(type="reasoning", text=delta["reasoning_content"]))

            # function calling:参数按 index 增量累积
            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", 0)
                slot = state.setdefault(f"tc_{idx}", {"id": "", "name": "", "arguments": ""})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["name"] += fn["name"]
                if fn.get("arguments"):
                    slot["arguments"] += fn["arguments"]

            finish = choice.get("finish_reason")
            if finish == "tool_calls":
                for key in sorted(k for k in state if k.startswith("tc_")):
                    s = state[key]
                    events.append(StreamEvent(
                        type="tool_call",
                        tool_call=ToolCall(id=s["id"], name=s["name"], arguments=s["arguments"]),
                    ))
                state.clear()

        if chunk.get("usage"):
            events.append(StreamEvent(type="done", usage=chunk["usage"]))
        return events
