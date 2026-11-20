"""统一内部数据契约 —— 三个协议适配器的公共语言。

上层(App/Agent)只使用这里定义的:
- Message:统一的消息(角色 + 文本/多模态内容 + 工具调用)
- ToolSpec:统一的工具定义
- StreamEvent:统一的流式事件(文本 / 思考 / 工具调用 / 完成 / 错误)

每个适配器负责:各自协议 -> 这套契约(入站)、这套契约 -> 各自协议(出站)。
这样新增第 4 种协议时,只要再写一个适配器,上层零改动。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str = ""          # JSON 字符串(增量累积后由适配器填充)


@dataclass
class Message:
    role: str                    # system | user | assistant | tool
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str = ""       # role=tool 时对应的调用 id
    name: str = ""               # role=tool 时的工具名(部分协议需要)

    @classmethod
    def from_dict(cls, d: dict) -> "Message":
        return cls(
            role=d.get("role", "user"),
            content=d.get("content", "") or "",
            tool_calls=[ToolCall(**tc) if isinstance(tc, dict) else tc
                        for tc in d.get("tool_calls", [])],
            tool_call_id=d.get("tool_call_id", ""),
            name=d.get("name", ""),
        )


@dataclass
class ToolSpec:
    """统一的工具(function)定义,OpenAI 风格,适配器各自翻译。"""
    name: str
    description: str = ""
    parameters: dict = field(default_factory=dict)   # JSON Schema

    @classmethod
    def from_dict(cls, d: dict) -> "ToolSpec":
        # 兼容 OpenAI 的 {"type":"function","function":{...}} 包装
        fn = d.get("function", d)
        return cls(
            name=fn.get("name", ""),
            description=fn.get("description", ""),
            parameters=fn.get("parameters", {}),
        )


@dataclass
class StreamEvent:
    """统一的流式事件。"""
    type: str                    # content | reasoning | tool_call | done | error
    text: str = ""               # content/reasoning 的文本
    tool_call: ToolCall | None = None
    usage: dict | None = None
    raw: Any = None

    def to_dict(self) -> dict:
        out = {"type": self.type}
        if self.text:
            out["text"] = self.text
        if self.tool_call is not None:
            out["tool_call"] = {
                "id": self.tool_call.id,
                "name": self.tool_call.name,
                "arguments": self.tool_call.arguments,
            }
        if self.usage is not None:
            out["usage"] = self.usage
        return out
