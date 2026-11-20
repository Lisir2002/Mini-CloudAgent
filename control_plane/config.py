"""控制面配置。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass
class ControlConfig:
    host: str = field(default_factory=lambda: _env("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(_env("PORT", "8000")))

    # 配对码 -> 用户ID 的映射(演示用,生产应存数据库)
    # 格式: PAIR_CODES=CODE1:user1,CODE2:user2
    pair_codes: dict[str, str] = field(default_factory=dict)

    # 节点 token 有效期(秒),0 表示永不过期
    token_ttl: int = field(default_factory=lambda: int(_env("TOKEN_TTL", "0")))

    def __post_init__(self):
        raw = _env("PAIR_CODES", "")
        for item in raw.split(","):
            if ":" in item:
                code, uid = item.split(":", 1)
                self.pair_codes[code.strip()] = uid.strip()
        # 演示默认配对码
        if not self.pair_codes:
            self.pair_codes["DEMO2026"] = "demo-user"
