"""模型配置 —— 协议无关。

用户只填:协议类型(protocol)、厂商(base_url)、密钥、模型名。
平台用适配器抹平三家协议的差异,用户不关心底层是 OpenAI / Anthropic / Gemini 哪种格式。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


# 支持的协议类型
PROTOCOLS = ("openai", "anthropic", "gemini")


def _norm_protocol(value: str) -> str:
    v = (value or "").strip().lower()
    aliases = {
        "oai": "openai",
        "openai-compatible": "openai",
        "claude": "anthropic",
        "gemini": "gemini",
        "google": "gemini",
        "vertex": "gemini",
    }
    v = aliases.get(v, v)
    return v if v in PROTOCOLS else "openai"


@dataclass
class ModelConfig:
    """用户在 App 里自定义的一个模型接入。

    protocol 决定用哪个适配器;其余字段原样传给适配器。
    不预设任何厂商 —— base_url 由用户自己填,可以是运营商、官方、聚合平台或自建服务。
    """
    api_key: str = ""
    model: str = ""
    base_url: str = ""
    protocol: str = "openai"          # openai | anthropic | gemini

    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: int = 120

    # 透传给底层 API 的额外参数(如 reasoning、top_p 等)
    extra_body: dict = field(default_factory=dict)

    # 显示名(可选,App 列表里展示)
    label: str = ""

    def __post_init__(self):
        self.protocol = _norm_protocol(self.protocol)

    @classmethod
    def from_dict(cls, data: dict) -> "ModelConfig":
        return cls(
            api_key=data.get("api_key", os.environ.get("MODEL_API_KEY", "")),
            model=data.get("model", os.environ.get("MODEL_NAME", "")),
            base_url=data.get("base_url", os.environ.get("MODEL_BASE_URL", "")),
            protocol=data.get("protocol", os.environ.get("MODEL_PROTOCOL", "openai")),
            temperature=float(data.get("temperature", 0.7)),
            max_tokens=int(data.get("max_tokens", 4096)),
            timeout=int(data.get("timeout", 120)),
            extra_body=data.get("extra_body", {}),
            label=data.get("label", ""),
        )

    def to_dict(self) -> dict:
        return {
            "api_key": "***" if self.api_key else "",
            "model": self.model,
            "base_url": self.base_url,
            "protocol": self.protocol,
            "label": self.label,
        }


# 仅作为"填写示例"存在,不构成任何绑定 —— 用户可自由改成任意兼容端点
PROTOCOL_EXAMPLES: dict[str, dict[str, str]] = {
    "openai": {
        "label": "OpenAI 兼容协议",
        "base_url_hint": "https://ai.ctaigw.cn/coding/v1  (或任意 /v1 兼容端点)",
        "note": "三家运营商 MaaS、OpenAI、通义、DeepSeek 等多为此协议",
    },
    "anthropic": {
        "label": "Anthropic Messages 协议",
        "base_url_hint": "https://api.anthropic.com/v1",
        "note": "Claude 系列;带 x-api-key 与 anthropic-version 头",
    },
    "gemini": {
        "label": "Gemini 协议",
        "base_url_hint": "https://generativelanguage.googleapis.com/v1beta",
        "note": "Google Gemini;streamGenerateContent 接口",
    },
}
