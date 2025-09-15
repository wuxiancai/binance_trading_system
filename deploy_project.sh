#!/bin/bash
# 币安交易系统项目部署脚本
# 用于下载代码、安装依赖、配置环境

set -e  # 遇到错误立即退出

# 配置变量
PROJECT_NAME="binance_trading_system"
DEPLOY_USER="$(whoami)"  # 使用当前用户
DEPLOY_DIR="$HOME/${PROJECT_NAME}"
GIT_REPO="https://github.com/your-username/${PROJECT_NAME}.git"  # 请替换为实际的 Git 仓库地址
SERVICE_PORT=5000

echo "=== 开始部署币安交易系统 ==="

# 创建部署目录
echo "[1/7] 创建部署目录..."
mkdir -p "$DEPLOY_DIR"

# 下载项目代码（如果是从 Git 仓库）
echo "[2/7] 下载项目代码..."
if [ -n "$GIT_REPO" ] && [ "$GIT_REPO" != "https://github.com/your-username/${PROJECT_NAME}.git" ]; then
    git clone "$GIT_REPO" "$DEPLOY_DIR" || {
        echo "Git 克隆失败，请手动将项目文件复制到 $DEPLOY_DIR"
        echo "或者更新脚本中的 GIT_REPO 变量"
    }
else
    echo "请手动将项目文件复制到 $DEPLOY_DIR 目录"
    echo "或者更新脚本中的 GIT_REPO 变量为实际的 Git 仓库地址"
fi

# 创建虚拟环境
echo "[3/7] 创建 Python 虚拟环境..."
cd "$DEPLOY_DIR"
# 确保使用 pyenv 管理的 Python
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"
python -m venv .venv

# 安装 Python 依赖
echo "[4/7] 安装 Python 依赖..."
cd "$DEPLOY_DIR" && source .venv/bin/activate
# 升级虚拟环境中的 pip
python -m pip install --upgrade pip
pip install -r requirements.txt

# 创建配置文件
echo "[5/7] 创建配置文件..."
if [ ! -f "$DEPLOY_DIR/.env" ]; then
    cp "$DEPLOY_DIR/.env.example" "$DEPLOY_DIR/.env"
    echo "已创建 .env 配置文件，请根据实际情况修改配置"
else
    echo ".env 配置文件已存在"
fi

# 创建日志目录
echo "[6/7] 创建日志目录..."
mkdir -p "$DEPLOY_DIR/logs"

# 设置文件权限
echo "[7/7] 设置文件权限..."
chmod +x "$DEPLOY_DIR/main.py"

# 创建启动脚本
echo "创建启动脚本..."
tee "$DEPLOY_DIR/start.sh" > /dev/null << EOF
#!/bin/bash
cd "$DEPLOY_DIR"
source .venv/bin/activate
export PYTHONPATH="$DEPLOY_DIR"
python main.py
EOF

chmod +x "$DEPLOY_DIR/start.sh"

echo "=== 项目部署完成 ==="
echo "部署目录: $DEPLOY_DIR"
echo "运行用户: $DEPLOY_USER"
echo "服务端口: $SERVICE_PORT"
echo ""
echo "下一步:"
echo "1. 编辑 $DEPLOY_DIR/.env 配置文件"
echo "2. 运行 systemd 服务配置脚本"
echo "3. 启动服务: sudo systemctl start $PROJECT_NAME"