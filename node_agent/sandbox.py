"""沙箱抽象 + 两种自研实现。

BaseSandbox 是"手"的能力契约:开会话、跑代码、读写文件、关会话。
DockerSandbox:生产环境,每个会话一个隔离容器。
LocalSandbox :开发/无Docker环境的降级实现,用独立进程 + 工作目录隔离。

后期接入"手机本地沙箱"时,只要再写一个实现了 BaseSandbox 的类即可,
节点Agent与控制面一行都不用改 —— 这就是抽象层的价值。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator

from shared import ErrorCodes, ProtocolError

from .config import AgentConfig
from .executors import Language, build_command


@dataclass
class SandboxSession:
    session_id: str
    workdir: str
    created_at: float = field(default_factory=lambda: asyncio.get_event_loop().time())
    metadata: dict = field(default_factory=dict)


class BaseSandbox(ABC):
    """沙箱后端契约。所有实现必须满足这套方法签名。"""

    backend_name: str = "base"

    def __init__(self, config: AgentConfig):
        self.config = config
        self.sessions: dict[str, SandboxSession] = {}

    @abstractmethod
    async def create_session(self, metadata: dict | None = None) -> SandboxSession:
        ...

    @abstractmethod
    async def close_session(self, session_id: str) -> None:
        ...

    @abstractmethod
    def run(
        self,
        session_id: str,
        code: str,
        language: Language = Language.PYTHON,
        timeout: int | None = None,
    ) -> AsyncIterator[dict]:
        """异步生成器,逐帧产出 {'stream':'stdout'|'stderr', 'text':str}。"""
        ...

    @abstractmethod
    async def read_file(self, session_id: str, path: str) -> str:
        ...

    @abstractmethod
    async def write_file(self, session_id: str, path: str, content: str) -> None:
        ...

    @abstractmethod
    async def list_files(self, session_id: str, path: str = ".") -> list[dict]:
        ...

    async def interrupt(self, session_id: str) -> bool:
        """中断会话中的任务,默认不支持。"""
        return False

    def _get_session(self, session_id: str) -> SandboxSession:
        s = self.sessions.get(session_id)
        if s is None:
            raise ProtocolError(ErrorCodes.SESSION_NOT_FOUND)
        return s

    def _safe_path(self, session: SandboxSession, path: str) -> Path:
        """防止路径穿越:所有文件操作限制在会话工作目录内。"""
        root = Path(session.workdir).resolve()
        target = (root / path).resolve()
        if target != root and root not in target.parents:
            raise ProtocolError(ErrorCodes.FILE_ERROR, "路径越界")
        return target

    async def capabilities(self) -> dict:
        return {
            "backend": self.backend_name,
            "languages": [lang.value for lang in Language],
            "max_sessions": self.config.max_sessions,
        }


class LocalSandbox(BaseSandbox):
    """本地进程沙箱:每个会话一个独立工作目录 + 独立子进程。

    隔离强度弱于 Docker,但零依赖、开箱即用,用于开发联调和低配环境。
    """

    backend_name = "local"

    async def create_session(self, metadata: dict | None = None) -> SandboxSession:
        sid = uuid.uuid4().hex
        workdir = os.path.join(self.config.workdir, sid)
        os.makedirs(workdir, exist_ok=True)
        session = SandboxSession(session_id=sid, workdir=workdir, metadata=metadata or {})
        self.sessions[sid] = session
        return session

    async def close_session(self, session_id: str) -> None:
        session = self._get_session(session_id)
        process = session.metadata.get("process")
        if process and process.returncode is None:
            process.kill()
        shutil.rmtree(session.workdir, ignore_errors=True)
        self.sessions.pop(session_id, None)

    async def run(
        self,
        session_id: str,
        code: str,
        language: Language = Language.PYTHON,
        timeout: int | None = None,
    ) -> AsyncIterator[dict]:
        session = self._get_session(session_id)
        timeout = timeout or self.config.exec_timeout
        cmd = build_command(code, language)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=session.workdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        session.metadata["process"] = proc

        async def pump(stream: asyncio.StreamReader, label: str):
            while True:
                line = await stream.readline()
                if not line:
                    break
                yield {"stream": label, "text": line.decode("utf-8", "replace")}

        async def merged():
            tasks = [asyncio.create_task(pump(proc.stdout, "stdout").__anext__()),
                     asyncio.create_task(pump(proc.stderr, "stderr").__anext__())]
            pending = {t: label for t, label in zip(tasks, ["stdout", "stderr"])}
            while pending:
                done, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for t in done:
                    label = pending.pop(t)
                    try:
                        item = t.result()
                        yield item
                    except StopAsyncIteration:
                        continue
                    # 重新挂上下一帧
                    nt = asyncio.create_task(
                        pump(proc.stdout if label == "stdout" else proc.stderr, label).__anext__()
                    )
                    pending[nt] = label

        try:
            async for item in self._with_timeout(merged(), timeout):
                yield item
            await proc.wait()
        except asyncio.TimeoutError:
            proc.kill()
            yield {"stream": "stderr", "text": f"\n[timeout] 执行超过 {timeout} 秒,已终止\n"}
        finally:
            session.metadata.pop("process", None)

    async def _with_timeout(self, agen: AsyncIterator[dict], timeout: int) -> AsyncIterator[dict]:
        """给异步生成器加整体超时。"""
        it = agen.__anext__()
        loop = asyncio.get_event_loop()
        while True:
            try:
                item = await asyncio.wait_for(it, timeout=timeout)
                yield item
                it = agen.__anext__()
            except StopAsyncIteration:
                break

    async def read_file(self, session_id: str, path: str) -> str:
        session = self._get_session(session_id)
        target = self._safe_path(session, path)
        try:
            return target.read_text(encoding="utf-8")
        except OSError as exc:
            raise ProtocolError(ErrorCodes.FILE_ERROR, str(exc)) from exc

    async def write_file(self, session_id: str, path: str, content: str) -> None:
        session = self._get_session(session_id)
        target = self._safe_path(session, path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise ProtocolError(ErrorCodes.FILE_ERROR, str(exc)) from exc

    async def list_files(self, session_id: str, path: str = ".") -> list[dict]:
        session = self._get_session(session_id)
        target = self._safe_path(session, path)
        if not target.exists():
            return []
        out = []
        for p in sorted(target.iterdir()):
            out.append({
                "name": p.name,
                "is_dir": p.is_dir(),
                "size": p.stat().st_size if p.is_file() else 0,
            })
        return out

    async def interrupt(self, session_id: str) -> bool:
        session = self._get_session(session_id)
        proc = session.metadata.get("process")
        if proc and proc.returncode is None:
            proc.kill()
            return True
        return False


class DockerSandbox(BaseSandbox):
    """Docker 沙箱:每个会话一个独立容器,硬件资源共享但进程/文件系统隔离。

    通过 docker CLI 驱动(不依赖 docker-py),保持零第三方依赖。
    容器以 --rm 启动,退出即销毁,避免残留。
    """

    backend_name = "docker"
    IMAGE = "agent-runtime-sandbox:latest"

    async def create_session(self, metadata: dict | None = None) -> SandboxSession:
        sid = uuid.uuid4().hex
        # 先在宿主机建一个挂载目录,供容器读写
        host_dir = os.path.join(self.config.workdir, sid)
        os.makedirs(host_dir, exist_ok=True)
        session = SandboxSession(
            session_id=sid,
            workdir=host_dir,
            metadata={**(metadata or {}), "container": f"agent-sbx-{sid[:12]}"},
        )
        self.sessions[sid] = session
        return session

    async def close_session(self, session_id: str) -> None:
        session = self._get_session(session_id)
        container = session.metadata.get("container")
        if container:
            await self._docker("rm", "-f", container)
        shutil.rmtree(session.workdir, ignore_errors=True)
        self.sessions.pop(session_id, None)

    async def _docker(self, *args: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            "docker", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise ProtocolError(ErrorCodes.SANDBOX_ERROR, err.decode("utf-8", "replace"))
        return out.decode("utf-8", "replace")

    async def run(
        self,
        session_id: str,
        code: str,
        language: Language = Language.PYTHON,
        timeout: int | None = None,
    ) -> AsyncIterator[dict]:
        session = self._get_session(session_id)
        timeout = timeout or self.config.exec_timeout
        container = session.metadata["container"]
        cmd = build_command(code, language)

        # 容器不存在则创建(带工作目录挂载),存在则直接用
        try:
            await self._docker("inspect", container)
        except ProtocolError:
            await self._docker(
                "run", "-d", "--name", container,
                "-v", f"{session.workdir}:/workspace",
                "-w", "/workspace",
                self.IMAGE,
                "tail", "-f", "/dev/null",
            )

        docker_cmd = ["docker", "exec", container, *cmd]
        proc = await asyncio.create_subprocess_exec(
            *docker_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        session.metadata["process"] = proc

        async def pump(stream: asyncio.StreamReader, label: str):
            while True:
                line = await stream.readline()
                if not line:
                    break
                yield {"stream": label, "text": line.decode("utf-8", "replace")}

        try:
            tasks = [
                asyncio.create_task(self._collect(pump(proc.stdout, "stdout"))),
                asyncio.create_task(self._collect(pump(proc.stderr, "stderr"))),
            ]
            results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=timeout)
            for group in results:
                for item in group:
                    yield item
        except asyncio.TimeoutError:
            proc.kill()
            await self._docker("rm", "-f", container)
            session.metadata.pop("container", None)
            yield {"stream": "stderr", "text": f"\n[timeout] 执行超过 {timeout} 秒,容器已销毁\n"}
        finally:
            session.metadata.pop("process", None)

    async def _collect(self, agen: AsyncIterator[dict]) -> list[dict]:
        return [item async for item in agen]

    async def read_file(self, session_id: str, path: str) -> str:
        session = self._get_session(session_id)
        target = self._safe_path(session, path)
        return target.read_text(encoding="utf-8")

    async def write_file(self, session_id: str, path: str, content: str) -> None:
        session = self._get_session(session_id)
        target = self._safe_path(session, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    async def list_files(self, session_id: str, path: str = ".") -> list[dict]:
        session = self._get_session(session_id)
        target = self._safe_path(session, path)
        if not target.exists():
            return []
        return [
            {"name": p.name, "is_dir": p.is_dir(), "size": p.stat().st_size if p.is_file() else 0}
            for p in sorted(target.iterdir())
        ]

    async def interrupt(self, session_id: str) -> bool:
        session = self._get_session(session_id)
        proc = session.metadata.get("process")
        if proc and proc.returncode is None:
            proc.kill()
            return True
        return False


async def docker_available() -> bool:
    """探测本机是否可用 Docker。"""
    if shutil.which("docker") is None:
        return False
    proc = await asyncio.create_subprocess_exec(
        "docker", "info",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    return await proc.wait() == 0


async def create_sandbox(config: AgentConfig) -> BaseSandbox:
    """按配置选择后端。auto 模式自动探测 Docker。"""
    backend = config.sandbox_backend
    if backend == "auto":
        backend = "docker" if await docker_available() else "local"
    if backend == "docker":
        return DockerSandbox(config)
    if backend == "local":
        return LocalSandbox(config)
    raise ProtocolError(ErrorCodes.SANDBOX_ERROR, f"未知沙箱后端: {backend}")
