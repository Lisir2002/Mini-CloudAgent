"""Gemini 协议适配器。

差异点(已全部抹平):
- 接口:POST {base}/models/{model}:streamGenerateContent?alt=sse&key=...
- 角色:user / model(assistant 对应 model)
- system 用 systemInstruction
- 工具:tools:[{functionDeclarations:[{name,description,parameters}]}]
- 工具调用:content.parts[].functionCall.{name,args}(args 是对象不是字符串)
"""

from __future__ import annotations

import json
from urllib.parse import quote

from ..base import BaseModelAdapter
from ..types import Message, StreamEvent, ToolCall, ToolSpec


class GeminiAdapter(BaseModelAdapter):
    protocol = "gemini"

    def build_request(self, messages: list[Message], tools: list[ToolSpec] | None,
                      stream: bool) -> tuple[str, dict, dict]:
        base = self.config.base_url.rstrip("/")
        # 兼容用户填了 /v1beta 或根地址两种情况
        if "/models/" not in base:
            base = f"{base}/models"
        model = quote(self.config.model, safe="")
        method = "streamGenerateContent" if stream else "generateContent"
        url = f"{base}/{model}:{method}"
        # key 通过 query 传(Gemini 标准),也支持 header
        url = f"{url}?alt=sse&key={quote(self.config.api_key, safe='')}"

        body: dict = {
            "contents": self._serialize_contents(messages),
            "generationConfig": {
                "temperature": self.config.temperature,
                "maxOutputTokens": self.config.max_tokens,
            },
        }
        system_text = "\n\n".join(m.content for m in messages if m.role == "system" and m.content)
        if system_text:
            body["systemInstruction"] = {"parts": [{"text": system_text}]}
        if tools:
            body["tools"] = [{
                "functionDeclarations": [
                    {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    }
                    for t in tools
                ]
            }]
        body.update(self.config.extra_body)

        headers = {"Content-Type": "application/json"}
        return url, headers, body

    def _serialize_contents(self, messages: list[Message]) -> list[dict]:
        out: list[dict] = []
        for m in messages:
            if m.role == "system":
                continue
            if m.role == "tool":
                # 工具结果:functionResponse part
                try:
                    resp = json.loads(m.content) if m.content else {}
                except json.JSONDecodeError:
                    resp = {"result": m.content}
                out.append({
                    "role": "user",
                    "parts": [{"functionResponse": {"name": m.name, "response": resp}}],
                })
            elif m.tool_calls:
                parts = []
                if m.content:
                    parts.append({"text": m.content})
                for tc in m.tool_calls:
                    try:
                        args = json.loads(tc.arguments) if tc.arguments else {}
                    except json.JSONDecodeError:
                        args = {}
                    parts.append({"functionCall": {"name": tc.name, "args": args}})
                out.append({"role": "model", "parts": parts})
            else:
                role = "model" if m.role == "assistant" else "user"
                out.append({"role": role, "parts": [{"text": m.content}]})
        return out

    def parse_sse_data(self, data: str, state: dict) -> list[StreamEvent]:
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            return []
        return self._parse_chunk(chunk, state)

    def _parse_chunk(self, chunk: dict, state: dict) -> list[StreamEvent]:
        events: list[StreamEvent] = []
        for candidate in chunk.get("candidates") or []:
            content = candidate.get("content") or {}
            for part in content.get("parts") or []:
                if part.get("text"):
                    events.append(StreamEvent(type="content", text=part["text"]))
                if "functionCall" in part:
                    fc = part["functionCall"]
                    args = fc.get("args", {})
                    events.append(StreamEvent(
                        type="tool_call",
                        tool_call=ToolCall(
                            id=fc.get("id", ""),
                            name=fc.get("name", ""),
                            arguments=json.dumps(args, ensure_ascii=False),
                        ),
                    ))
            # Gemini 的 finishReason:STOP / MAX_TOKENS 等
            if candidate.get("finishReason"):
                state["finish"] = candidate["finishReason"]
        if chunk.get("usageMetadata"):
            events.append(StreamEvent(type="done", usage=chunk["usageMetadata"]))
        return events
