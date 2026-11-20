"""代码执行器:把一段代码翻译成可执行的命令。

自研实现,支持多语言;代码通过 stdin 传给解释器,避免命令注入和转义地狱。
"""

from __future__ import annotations

import shlex
from enum import Enum


class Language(str, Enum):
    PYTHON = "python"
    SHELL = "shell"
    NODE = "node"
    BASH = "bash"


LANG_ALIASES = {
    "py": Language.PYTHON,
    "python3": Language.PYTHON,
    "js": Language.NODE,
    "javascript": Language.NODE,
    "sh": Language.SHELL,
    "bash": Language.BASH,
    "cmd": Language.SHELL,
}


def normalize_language(value: str | Language) -> Language:
    if isinstance(value, Language):
        return value
    v = value.strip().lower()
    return LANG_ALIASES.get(v, Language(v) if v in {x.value for x in Language} else Language.PYTHON)


def build_command(code: str, language: Language | str) -> list[str]:
    """返回 argv 列表。代码经 stdin 喂入,这里只给出解释器命令。"""
    lang = normalize_language(language)
    if lang == Language.PYTHON:
        return ["python3", "-u", "-c", code]
    if lang in (Language.SHELL, Language.BASH):
        return ["bash", "-c", code]
    if lang == Language.NODE:
        return ["node", "-e", code]
    raise ValueError(f"不支持的语言: {lang}")


def describe_command(code: str, language: Language | str) -> str:
    """给人看的命令描述(日志/调试用)。"""
    return " ".join(shlex.quote(part) for part in build_command(code, language))


async def execute(sandbox, session_id: str, code: str, language: Language | str = Language.PYTHON,
                  timeout: int | None = None):
    """便捷函数:直接拿到一个沙箱会话并执行代码,返回输出字典列表。"""
    return [item async for item in sandbox.run(session_id, code, normalize_language(language), timeout)]
