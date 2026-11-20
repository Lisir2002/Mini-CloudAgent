#!/usr/bin/env bash
# 节点Agent 一键安装脚本
#
# 用法(在用户自己的服务器上):
#   curl -fsSL https://raw.githubusercontent.com/Lisir2002/Mini-CloudAgent/main/scripts/install_node.sh | bash
#
# 然后按提示填入从 App 获取的配对码,脚本会:
#   1. 克隆仓库 / 拉取最新代码
#   2. 创建 Python 虚拟环境并安装依赖
#   3. 写入 systemd 服务,开机自启、断线自动重连
#   4. 启动节点Agent

set -euo pipefail

REPO="https://github.com/Lisir2002/Mini-CloudAgent.git"
INSTALL_DIR="${INSTALL_DIR:-$HOME/mini-cloudagent}"
CONTROL_URL="${CONTROL_URL:-ws://127.0.0.1:8000/ws/node}"
SERVICE_NAME="mini-cloudagent-node"

echo "=== Mini-CloudAgent 节点Agent 安装 ==="

# 1. 获取代码
if [ -d "$INSTALL_DIR/.git" ]; then
  echo "[1/4] 更新代码..."
  git -C "$INSTALL_DIR" pull --ff-only
else
  echo "[1/4] 克隆代码到 $INSTALL_DIR ..."
  git clone "$REPO" "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"

# 2. Python 环境
echo "[2/4] 准备 Python 环境..."
PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "未找到 python3,请先安装 Python 3.10+"; exit 1
fi
if [ ! -d .venv ]; then
  "$PYTHON" -m venv .venv
fi
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

# 3. 配对码 / token
echo "[3/4] 配置接入凭证..."
read -r -p "请输入 App 生成的配对码(已有 token 可直接回车跳过): " PAIR_CODE
read -r -p "请输入控制面地址 [${CONTROL_URL}]: " INPUT_URL
[ -n "$INPUT_URL" ] && CONTROL_URL="$INPUT_URL"

# 4. systemd 服务
echo "[4/4] 注册系统服务..."
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
if [ "$(id -u)" -eq 0 ]; then
  cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Mini-CloudAgent Node Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$INSTALL_DIR
Environment=CONTROL_URL=$CONTROL_URL
Environment=PAIR_CODE=$PAIR_CODE
Environment=SANDBOX_BACKEND=auto
ExecStart=$INSTALL_DIR/.venv/bin/python -m node_agent.run
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable "$SERVICE_NAME"
  systemctl restart "$SERVICE_NAME"
  echo "服务已启动。查看日志: journalctl -u $SERVICE_NAME -f"
else
  echo "非 root 运行,跳过 systemd。用 nohup 启动:"
  echo "  cd $INSTALL_DIR && PAIR_CODE=$PAIR_CODE CONTROL_URL=$CONTROL_URL nohup .venv/bin/python -m node_agent.run &"
fi

echo "=== 安装完成 ==="
