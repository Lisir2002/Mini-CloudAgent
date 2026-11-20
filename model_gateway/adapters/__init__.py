"""三个协议适配器。"""

from .openai import OpenAIAdapter
from .anthropic import AnthropicAdapter
from .gemini import GeminiAdapter

__all__ = ["OpenAIAdapter", "AnthropicAdapter", "GeminiAdapter"]
