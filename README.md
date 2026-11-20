# Agent Runtime —— 移动端 Agent 运行时

> 自研的"大脑 + 手"架构:移动端 App 配置大模型,云端沙箱执行 Agent 任务。
> 协议、节点Agent、控制面、沙箱执行器、模型网关**全部自研**,不依赖任何第三方沙箱服务。

## 核心设计

```
         App(大脑)
   会话 / 模型配置 / 任务分发
              │
      统一沙箱协议(JSON-RPC over WS)
              │
   ┌──────────┼──────────┐
   ▼          ▼          ▼
用户服务器   手机本地   平台托管    ← 三种"手"可插拔,上层零改动
(节点Agent) (后期接入)  (可选)
```

**一句话**:大脑只管发"执行这段 Python / 跑这条命令 / 读这个文件",谁在跑、在哪跑它不关心。三种沙箱后端都实现同一套协议,后期接入"手机本地沙箱"时上层代码一行不改。

## 目录结构

| 目录 | 职责 |
|---|---|
| `shared/` | 统一协议契约(JSON-RPC 消息、方法枚举、错误码)—— 自研 |
| `control_plane/` | 控制面:节点注册、会话管理、任务路由、配对码认证 |
| `node_agent/` | 节点Agent:主动外连、心跳、沙箱调度;含 Docker/本地两种沙箱 —— 自研 |
| `model_gateway/` | 模型网关:OpenAI / Anthropic / Gemini 三协议适配器 —— 自研 |
| `demo/` | 端到端联调脚本 |

## 模型网关:协议无关,用户自定义厂商

用户按自己接口的协议类型选择,厂商和模型完全自定义,平台不绑定任何一家:

```python
from model_gateway import ModelConfig, ModelGateway, Message

# 例:运营商 OpenAI 兼容端点(电信星辰/移动九天/联通元景都走这个)
cfg = ModelConfig(
    protocol="openai",
    base_url="https://ai.ctaigw.cn/coding/v1",   # 用户自己填
    api_key="<用户的KEY>",
    model="<模型名>",
)
# Claude
cfg = ModelConfig(protocol="anthropic", base_url="https://api.anthropic.com/v1", ...)
# Gemini
cfg = ModelConfig(protocol="gemini", base_url="https://generativelanguage.googleapis.com/v1beta", ...)

gw = ModelGateway(cfg)
async for ev in gw.chat_stream([Message(role="user", content="你好")]):
    print(ev.to_dict())   # 统一事件:content / reasoning / tool_call / done / error
```

三种协议的差异(请求格式、消息结构、SSE 事件、工具调用参数累积)全部由适配器抹平,上层只认统一消息和统一事件。新增第 4 种协议只需再写一个适配器。

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 端到端联调(无需 Docker,本地沙箱降级)

```bash
python -m demo.e2e_test
```

看到 `端到端联调通过` 即表示:大脑 ↔ 协议 ↔ 手 全链路正常。

### 3. 分别启动(生产形态)

```bash
# 终端1:控制面
python -m uvicorn control_plane.app:create_app --factory --port 8000

# 终端2:节点Agent(在自己服务器跑),先设配对码
PAIR_CODE=DEMO2026 CONTROL_URL=ws://<你的控制面>:8000/ws/node python -m node_agent.run
```

节点首次用配对码注册,换取长期 token 存到 `.node_token`,后续免配对自动重连。

## 节点Agent 配置(环境变量,方便 GitHub 一键脚本分发)

| 变量 | 说明 | 默认 |
|---|---|---|
| `CONTROL_URL` | 控制面 WebSocket 地址 | `ws://127.0.0.1:8000/ws/node` |
| `PAIR_CODE` | 首次注册配对码 | 空 |
| `NODE_LABEL` | 节点显示名 | `my-server` |
| `SANDBOX_BACKEND` | `auto`/`docker`/`local` | `auto`(有 Docker 用 Docker,否则本地) |
| `MAX_SESSIONS` | 最大并发会话 | 8 |
| `EXEC_TIMEOUT` | 单次执行超时(秒) | 120 |
| `WORKDIR` | 沙箱工作目录 | `./sandbox_work` |

## 沙箱后端说明

- **DockerSandbox**:每会话一个隔离容器,`--rm` 退出即销毁。需本机 Docker。
- **LocalSandbox**:独立进程 + 工作目录隔离,零依赖,用于开发/低配环境。
- **接入手机本地沙箱**:新写一个实现 `node_agent.sandbox.BaseSandbox` 的类即可,协议层和控制面无需改动。

## 与 GitHub 仓库对接

当前为空仓库起步。仓库链接确定后,可直接把本目录推上去。节点Agent 设计为**单文件启动 + 环境变量配置**,便于写一键安装脚本(下载/安装依赖/填配对码/注册 systemd 服务)。

## 状态

- [x] 统一协议层
- [x] 节点Agent + Docker/本地双沙箱
- [x] 控制面(注册/心跳/路由/配对码)
- [x] 模型网关(OpenAI/Anthropic/Gemini 三协议)
- [x] 端到端联调验证
- [ ] 手机本地沙箱接入(预留接口)
- [ ] App 客户端
