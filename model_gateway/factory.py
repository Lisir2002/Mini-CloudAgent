"""模型网关统一入口 —— 协议对上层完全透明。

上层只管:传一个 ModelConfig(用户自定义) + 统一消息,拿到统一流式事件。
用哪个协议、怎么翻译,由工厂选适配器决定。
"""

from __future__ import annotations

from typing import AsyncIterator

from shared import ErrorCodes, ProtocolError

from .adapters import AnthropicAdapter, GeminiAdapter, OpenAIAdapter
from .base import BaseModelAdapter
from .config import ModelConfig
from .types import Message, StreamEvent, ToolSpec

_ADAPTERS: dict[str, type[BaseModelAdapter]] = {
    "openai": OpenAIAdapter,
    "anthropic": AnthropicAdapter,
    "gemini": GeminiAdapter,
}


def create_adapter(config: ModelConfig) -> BaseModelAdapter:
    cls = _ADAPTERS.get(config.protocol)
    if not cls:
        raise ProtocolError(ErrorCodes.MODEL_API_ERROR, f"不支持的协议: {config.protocol}")
    return cls(config)


class ModelGateway:
    """对上层的统一门面。protocol 由 config 决定,上层不感知。"""

    def __init__(self, config: ModelConfig):
        self.config = config
        self.adapter = create_adapter(config)

    async def chat_stream(
        self, messages: list[Message | dict], tools: list[ToolSpec | dict] | None = None
    ) -> AsyncIterator[StreamEvent]:
        msgs = [m if isinstance(m, Message) else Message.from_dict(m) for m in messages]
        toolspecs = [t if isinstance(t, ToolSpec) else ToolSpec.from_dict(t) for t in (tools or [])]
        async for event in self.adapter.chat_stream(msgs, toolspecs):
            yield event

    async def chat(self, messages: list[Message | dict], tools: list[ToolSpec | dict] | None = None) -> dict:
        msgs = [m if isinstance(m, Message) else Message.from_dict(m) for m in messages]
        toolspecs = [t if isinstance(t, ToolSpec) else ToolSpec.from_dict(t) for t in (tools or [])]
        return await self.adapter.chat(msgs, toolspecs)


async def chat_stream(config: ModelConfig, messages: list, tools: list | None = None) -> AsyncIterator[dict]:
    """便捷函数:产出统一事件字典。"""
    async for event in ModelGateway(config).chat_stream(messages, tools):
        yield event.to_dict()
