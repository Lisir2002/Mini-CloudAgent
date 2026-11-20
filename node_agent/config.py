"""节点Agent配置。所有参数都能用环境变量覆盖,方便 GitHub 一键脚本分发。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class AgentConfig:
    # 控制面 WebSocket 地址(节点主动外连到这里)
    control_url: str = field(default_factory=lambda: _env("CONTROL_URL", "ws://127.0.0.1:8000/ws/node"))

    # 配对码:首次注册时用,换取长期 node_token
    pair_code: str = field(default_factory=lambda: _env("PAIR_CODE", ""))

    # 持久化后的 node_token(注册成功后写入本地,后续免配对)
    node_token: str = field(default_factory=lambda: _env("NODE_TOKEN", ""))
    token_file: str = field(default_factory=lambda: _env("TOKEN_FILE", ".node_token"))

    # 本机标签,展示在 App 的节点列表里
    label: str = field(default_factory=lambda: _env("NODE_LABEL", "my-server"))

    # 沙箱后端:auto = 有 Docker 用 Docker,否则本地进程降级
    sandbox_backend: str = field(default_factory=lambda: _env("SANDBOX_BACKEND", "auto"))

    # 资源限制
    max_sessions: int = field(default_factory=lambda: _env_int("MAX_SESSIONS", 8))
    exec_timeout: int = field(default_factory=lambda: _env_int("EXEC_TIMEOUT", 120))
    max_output_bytes: int = field(default_factory=lambda: _env_int("MAX_OUTPUT_BYTES", 2 * 1024 * 1024))

    # 工作目录(本地沙箱的根)
    workdir: str = field(default_factory=lambda: _env("WORKDIR", "./sandbox_work"))

    def save_token(self, token: str) -> None:
        self.node_token = token
        try:
            with open(self.token_file, "w", encoding="utf-8") as f:
                f.write(token)
        except OSError:
            pass

    def load_token(self) -> str:
        if self.node_token:
            return self.node_token
        try:
            with open(self.token_file, "r", encoding="utf-8") as f:
                self.node_token = f.read().strip()
        except OSError:
            pass
        return self.node_token
