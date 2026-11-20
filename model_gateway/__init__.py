"""模型网关:协议无关的大模型接入层。

支持 OpenAI / Anthropic / Gemini 三种协议,用户自定义厂商与模型。
上层只认统一消息格式和统一流式事件,底层协议差异由适配器抹平。
"""

from .config import ModelConfig, PROTOCOLS, PROTOCOL_EXAMPLES
from .types import Message, ToolCall, ToolSpec, StreamEvent
from .base import BaseModelAdapter
from .adapters import OpenAIAdapter, AnthropicAdapter, GeminiAdapter
from .factory import ModelGateway, create_adapter, chat_stream

__all__ = [
    "ModelConfig",
    "PROTOCOLS",
    "PROTOCOL_EXAMPLES",
    "Message",
    "ToolCall",
    "ToolSpec",
    "StreamEvent",
    "BaseModelAdapter",
    "OpenAIAdapter",
    "AnthropicAdapter",
    "GeminiAdapter",
    "ModelGateway",
    "create_adapter",
    "chat_stream",
]
