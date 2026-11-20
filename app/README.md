# Mini CloudAgent App

移动端客户端:配置自己的模型 API,通过控制面让云端沙箱执行 Agent 任务。基于 Expo(React Native),支持 Android / iOS 真机。

## 一、真机测试(Expo Go,最快捷)

不用编译原生包,手机装 Expo Go 扫码即可。

### 前提
1. 手机装 **Expo Go**(App Store / Google Play 搜 "Expo Go")
2. 电脑和手机在**同一个 WiFi**(局域网模式),或手机能访问电脑

### 步骤

**1. 电脑端启动控制面**(仓库根目录):
```bash
python -m uvicorn control_plane.app:create_app --factory --host 0.0.0.0 --port 8000
```
记下电脑的局域网 IP(如 `192.168.1.10`),Windows 用 `ipconfig`,Mac/Linux 用 `ifconfig`。

**2. 启动节点Agent**(你自己的服务器,或就在电脑上测):
```bash
PAIR_CODE=DEMO2026 CONTROL_URL=ws://127.0.0.1:8000/ws/node \
  python -m node_agent.run
```
看到「注册成功」即上线。

**3. 启动 App 开发服务器**:
```bash
cd app
npm install
npx expo start --lan
```
终端会显示一个二维码。

**4. 手机扫码**:
- Android:Expo Go 内点「Scan QR code」扫
- iPhone:用相机扫(会跳转 Expo Go)

如果扫码连不上(局域网隔离/防火墙),改用 tunnel 模式:
```bash
npx expo start --tunnel
```
(tunnel 走公网中转,手机无需和电脑同网,但首次稍慢)

### 5. App 内配置
打开 App → 「配置」Tab:
- **控制面地址**:填 `ws://<电脑局域网IP>:8000/ws/client`,如 `ws://192.168.1.10:8000/ws/client`
  - 若用 tunnel 且控制面也在公网,填公网 ws 地址
- **新增模型**:选协议(openai/anthropic/gemini)→ 填 Base URL、API Key、模型名 → 保存启用
  - 运营商 MaaS(电信星辰/移动九天/联通元景)多为 OpenAI 兼容,选 `openai`
- 切到「节点」Tab 点刷新,能看到节点上线即连通

### 6. 对话测试
「对话」Tab 顶部显示「沙箱已连接」后,输入:
> 帮我用 Python 计算 1 到 100 的和,并验证结果

观察:模型流式输出 → 触发 `execute_code` 工具 → 沙箱执行 → 输出回传 → 模型给出最终答案。

## 二、打包成独立 App(可选)

需要 Android Studio / Xcode 环境:
```bash
npx expo run:android    # 或 npx expo run:ios
```
或用 EAS 云打包:
```bash
npm install -g eas-cli
eas build -p android --profile preview
```

## 三、协议说明

App 端模型客户端与后端 `model_gateway` 完全对齐:
- 三协议适配器抹平请求格式差异,统一产出 content/reasoning/tool_call/done 事件
- 工具调用参数跨帧累积(OpenAI 的 arguments 增量、Anthropic 的 input_json_delta、Gemini 的 functionCall)
- 密钥存 Expo SecureStore(系统钥匙串),不落明文

## 四、已知限制

- 真机 HTTP(ws://)需 Android `usesCleartextTraffic`(已配置);iOS 若要求 HTTPS,需给控制面配 TLS 用 wss://
- 流式依赖 RN 的 `fetch` + `ReadableStream`,Expo SDK 52 支持;若个别机型不支持会返回错误提示,可改用非流式
- 默认用户 ID 为 `demo-user`,与控制面演示配对码 `DEMO2026` 对应
