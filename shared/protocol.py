"""统一沙箱协议 —— 自研的 JSON-RPC 风格消息契约。

设计原则:
1. 传输无关:同一套消息能跑在 WebSocket / TCP / 本地内存总线上,
   所以"手机本地沙箱"后期只要换传输层,协议不用动。
2. 强类型:所有 method 收进 Methods 枚举,所有错误码收进 ErrorCodes,
   避免字符串拼写错误在三种后端之间埋雷。
3. 流式一等公民:执行结果通过 stream.* 通知逐帧回传,支持边跑边看。

借鉴的是"控制面/执行面分离 + 统一 RPC 契约"这一思路,
消息结构和实现完全自研,不依赖任何第三方沙箱 SDK。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum, IntEnum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# 方法枚举
# ---------------------------------------------------------------------------

class Methods(str, Enum):
    """所有合法的方法名。控制面与节点Agent都从这一个枚举取,杜绝拼写漂移。"""

    # ---- 节点生命周期(节点 -> 控制面)----
    NODE_REGISTER = "node.register"        # 节点携带配对码注册,取得 node_id
    NODE_HEARTBEAT = "node.heartbeat"      # 心跳,附带负载指标

    # ---- 会话 / 沙箱生命周期(客户端 -> 控制面 -> 节点)----
    SESSION_CREATE = "session.create"      # 创建一个沙箱会话
    SESSION_CLOSE = "session.close"        # 关闭并销毁会话
    SESSION_LIST = "session.list"          # 列出当前会话

    # ---- 执行(核心能力)----
    EXEC_RUN = "exec.run"                  # 执行代码/命令,结果以 stream.* 回传
    EXEC_INTERRUPT = "exec.interrupt"      # 中断正在执行的任务

    # ---- 文件操作 ----
    FILE_READ = "file.read"
    FILE_WRITE = "file.write"
    FILE_LIST = "file.list"
    FILE_DELETE = "file.delete"

    # ---- 流式通知(节点/控制面 -> 客户端)----
    STREAM_OUTPUT = "stream.output"        # 一段 stdout/stderr 输出
    STREAM_EVENT = "stream.event"          # 生命周期事件:started/done/error

    # ---- 能力协商 ----
    CAPABILITIES_GET = "capabilities.get"  # 查询后端支持的语言/能力


# 流式通知方法集合(用于快速判断一条消息是不是流式帧)
STREAM_METHODS = {Methods.STREAM_OUTPUT, Methods.STREAM_EVENT}


# ---------------------------------------------------------------------------
# 错误码
# ---------------------------------------------------------------------------

class ErrorCodes(IntEnum):
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    # 业务错误(自研段:1000+)
    NODE_NOT_FOUND = 1001
    NODE_BUSY = 1002
    PAIR_CODE_INVALID = 1003
    SESSION_NOT_FOUND = 1004
    SESSION_LIMIT = 1005
    SANDBOX_ERROR = 1006
    EXEC_FAILED = 1007
    FILE_ERROR = 1008
    MODEL_API_ERROR = 1009
    TIMEOUT = 1010


_ERROR_MESSAGES = {
    ErrorCodes.PARSE_ERROR: "解析 JSON 失败",
    ErrorCodes.INVALID_REQUEST: "无效的请求",
    ErrorCodes.METHOD_NOT_FOUND: "方法不存在",
    ErrorCodes.INVALID_PARAMS: "参数不合法",
    ErrorCodes.INTERNAL_ERROR: "内部错误",
    ErrorCodes.NODE_NOT_FOUND: "没有可用的节点",
    ErrorCodes.NODE_BUSY: "节点繁忙",
    ErrorCodes.PAIR_CODE_INVALID: "配对码无效或已过期",
    ErrorCodes.SESSION_NOT_FOUND: "会话不存在",
    ErrorCodes.SESSION_LIMIT: "会话数已达上限",
    ErrorCodes.SANDBOX_ERROR: "沙箱错误",
    ErrorCodes.EXEC_FAILED: "执行失败",
    ErrorCodes.FILE_ERROR: "文件操作失败",
    ErrorCodes.MODEL_API_ERROR: "模型 API 调用失败",
    ErrorCodes.TIMEOUT: "超时",
}


def error_message(code: int) -> str:
    try:
        return _ERROR_MESSAGES[ErrorCodes(code)]
    except (ValueError, KeyError):
        return "未知错误"


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------

class ProtocolError(Exception):
    """协议层异常,带错误码,可直接转成 error 响应。"""

    def __init__(self, code: ErrorCodes, message: str | None = None, data: Any = None):
        self.code = code
        self.message = message or error_message(code)
        self.data = data
        super().__init__(f"[{code}] {self.message}")

    def to_dict(self) -> dict:
        err = {"code": int(self.code), "message": self.message}
        if self.data is not None:
            err["data"] = self.data
        return err


# ---------------------------------------------------------------------------
# 消息模型(纯 dataclass,零第三方依赖)
# ---------------------------------------------------------------------------

@dataclass
class RpcRequest:
    id: str
    method: str
    params: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"jsonrpc": "2.0", "id": self.id, "method": self.method, "params": self.params}


@dataclass
class RpcResponse:
    id: str
    result: Any = None

    def to_dict(self) -> dict:
        return {"jsonrpc": "2.0", "id": self.id, "result": self.result}


@dataclass
class RpcErrorResponse:
    id: Optional[str]
    error: dict

    def to_dict(self) -> dict:
        return {"jsonrpc": "2.0", "id": self.id, "error": self.error}


@dataclass
class RpcNotification:
    """无 id 的单向推送,用于流式输出。"""
    method: str
    params: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"jsonrpc": "2.0", "method": self.method, "params": self.params}


RpcMessage = RpcRequest | RpcResponse | RpcErrorResponse | RpcNotification


# ---------------------------------------------------------------------------
# 构造函数
# ---------------------------------------------------------------------------

def new_id() -> str:
    return uuid.uuid4().hex


def build_request(method: str | Methods, params: dict | None = None, rid: str | None = None) -> RpcRequest:
    m = method.value if isinstance(method, Methods) else method
    return RpcRequest(id=rid or new_id(), method=m, params=params or {})


def build_response(rid: str, result: Any) -> RpcResponse:
    return RpcResponse(id=rid, result=result)


def build_error(rid: str | None, code: ErrorCodes, message: str | None = None, data: Any = None) -> RpcErrorResponse:
    return RpcErrorResponse(id=rid, error=ProtocolError(code, message, data).to_dict())


def build_notification(method: str | Methods, params: dict | None = None) -> RpcNotification:
    m = method.value if isinstance(method, Methods) else method
    return RpcNotification(method=m, params=params or {})


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------

def parse_message(raw: str | bytes | dict) -> RpcMessage:
    """把一段 JSON 解析成具体的消息对象。"""
    if isinstance(raw, (str, bytes)):
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProtocolError(ErrorCodes.PARSE_ERROR, str(exc)) from exc
    elif isinstance(raw, dict):
        data = raw
    else:
        raise ProtocolError(ErrorCodes.INVALID_REQUEST, "消息必须是 JSON 字符串或字典")

    if not isinstance(data, dict) or data.get("jsonrpc") != "2.0":
        raise ProtocolError(ErrorCodes.INVALID_REQUEST, "缺少 jsonrpc=2.0")

    has_id = "id" in data
    is_response = "result" in data or "error" in data

    if is_response:
        rid = data.get("id")
        if "error" in data:
            return RpcErrorResponse(id=rid, error=data["error"])
        return RpcResponse(id=rid, result=data.get("result"))

    method = data.get("method")
    if not isinstance(method, str):
        raise ProtocolError(ErrorCodes.INVALID_REQUEST, "缺少 method")
    params = data.get("params") or {}
    if not isinstance(params, dict):
        raise ProtocolError(ErrorCodes.INVALID_PARAMS, "params 必须是对象")

    if has_id:
        return RpcRequest(id=str(data["id"]), method=method, params=params)
    return RpcNotification(method=method, params=params)


def to_json(msg: RpcMessage) -> str:
    """序列化为 JSON 字符串。"""
    if isinstance(msg, (RpcRequest, RpcResponse, RpcErrorResponse, RpcNotification)):
        return json.dumps(msg.to_dict(), ensure_ascii=False)
    raise TypeError(f"不支持的消息类型: {type(msg)}")
