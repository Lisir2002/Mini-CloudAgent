"""Anthropic Messages 协议适配器。

差异点(已全部抹平):
- system 是顶层字段,不在 messages 里
- 消息 content 可以是字符串或 block 列表
- assistant 的回复里工具调用是 tool_use block,工具结果是 tool_result block(放在 user 角色)
- SSE 有多种 event 类型:message_start / content_block_start / content_block_delta /
  content_block_stop / message_delta / message_stop
- 工具参数是 input_json_delta 分帧累积的 partial_json
"""

from __future__ import annotations

import json

from ..base import BaseModelAdapter
from ..types import Message, StreamEvent, ToolCall, ToolSpec


class AnthropicAdapter(BaseModelAdapter):
    protocol = "anthropic"
    API_VERSION = "2023-06-01"

    def build_request(self, messages: list[Message], tools: list[ToolSpec] | None,
                      stream: bool) -> tuple[str, dict, dict]:
        base = self.config.base_url.rstrip("/")
        if base.endswith("/messages"):
            url = base
        else:
            url = f"{base}/messages"

        # system 消息抽出来拼成顶层字符串
        system_text = "\n\n".join(m.content for m in messages if m.role == "system" and m.content)

        body: dict = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "system": system_text,
            "messages": self._serialize_messages(messages),
            "stream": stream,
        }
        if tools:
            body["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.parameters,
                }
                for t in tools
            ]
        body.update(self.config.extra_body)

        headers = {
            "x-api-key": self.config.api_key,
            "anthropic-version": self.API_VERSION,
            "Content-Type": "application/json",
        }
        return url, headers, body

    def _serialize_messages(self, messages: list[Message]) -> list[dict]:
        out: list[dict] = []
        for m in messages:
            if m.role == "system":
                continue  # system 走顶层
            if m.role == "tool":
                # 工具结果:user 角色 + tool_result block
                out.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": m.tool_call_id,
                        "content": m.content,
                    }],
                })
            elif m.role == "assistant" and m.tool_calls:
                blocks: list[dict] = []
                if m.content:
                    blocks.append({"type": "text", "text": m.content})
                for tc in m.tool_calls:
                    try:
                        inp = json.loads(tc.arguments) if tc.arguments else {}
                    except json.JSONDecodeError:
                        inp = {}
                    blocks.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": inp})
                out.append({"role": "assistant", "content": blocks})
            else:
                # user / 纯文本 assistant
                role = "assistant" if m.role == "assistant" else "user"
                out.append({"role": role, "content": m.content})
        return out

    def parse_sse_data(self, data: str, state: dict) -> list[StreamEvent]:
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            return []

        etype = chunk.get("_event") or chunk.get("type")
        events: list[StreamEvent] = []

        if etype == "content_block_start":
            block = chunk.get("content_block") or {}
            idx = chunk.get("index", 0)
            if block.get("type") == "tool_use":
                state[f"tool_{idx}"] = {
                    "id": block.get("id", ""),
                    "name": block.get("name", ""),
                    "arguments": "",
                }

        elif etype == "content_block_delta":
            delta = chunk.get("delta") or {}
            dtype = delta.get("type")
            if dtype == "text_delta":
                events.append(StreamEvent(type="content", text=delta.get("text", "")))
            elif dtype == "input_json_delta":
                idx = chunk.get("index", 0)
                slot = state.setdefault(f"tool_{idx}", {"id": "", "name": "", "arguments": ""})
                slot["arguments"] += delta.get("partial_json", "")

        elif etype == "content_block_stop":
            idx = chunk.get("index", 0)
            slot = state.pop(f"tool_{idx}", None)
            if slot:
                events.append(StreamEvent(
                    type="tool_call",
                    tool_call=ToolCall(id=slot["id"], name=slot["name"], arguments=slot["arguments"]),
                ))

        elif etype == "message_delta":
            delta = chunk.get("delta") or {}
            usage = chunk.get("usage") or {}
            # Anthropic 的 usage 在 message_delta 里出现,output_tokens 在这里
            if usage:
                events.append(StreamEvent(type="done", usage=usage))

        elif etype == "message_stop":
            if not any(e.type == "done" for e in events):
                events.append(StreamEvent(type="done"))

        return events
