#!/bin/bash
# Ubuntu Server 24 环境配置脚本
# 用于安装 Python 3.11+、pip、虚拟环境等必要组件

set -e  # 遇到错误立即退出

echo "=== 开始配置 Ubuntu Server 24 环境 ==="

# 更新系统包
echo "[1/6] 更新系统包..."
sudo apt update && sudo apt upgrade -y

# 安装基础工具
echo "[2/6] 安装基础工具..."
sudo apt install -y \
    curl \
    wget \
    git \
    unzip \
    build-essential \
    software-properties-common \
    apt-transport-https \
    ca-certificates \
    gnupg \
    lsb-release

# 安装 Python 构建依赖
echo "[3/8] 安装 Python 构建依赖..."
sudo apt install -y \
    make \
    build-essential \
    libssl-dev \
    zlib1g-dev \
    libbz2-dev \
    libreadline-dev \
    libsqlite3-dev \
    wget \
    curl \
    llvm \
    libncurses5-dev \
    libncursesw5-dev \
    xz-utils \
    tk-dev \
    libffi-dev \
    liblzma-dev \
    python3-openssl

# 安装 pyenv（Python 版本管理器）
echo "[4/8] 安装 pyenv..."
if [ ! -d "$HOME/.pyenv" ]; then
    curl https://pyenv.run | bash
    echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.bashrc
    echo 'command -v pyenv >/dev/null || export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.bashrc
    echo 'eval "$(pyenv init -)"' >> ~/.bashrc
    
    # 为 zsh 用户也添加配置
    if [ -f "$HOME/.zshrc" ]; then
        echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.zshrc
        echo 'command -v pyenv >/dev/null || export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.zshrc
        echo 'eval "$(pyenv init -)"' >> ~/.zshrc
    fi
else
    echo "pyenv 已安装"
fi

# 重新加载环境变量
echo "[5/8] 配置环境变量..."
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"

# 安装 Python 3.11.8（避免与系统 Python 冲突）
echo "[6/8] 安装 Python 3.11.8..."
if ! pyenv versions | grep -q "3.11.8"; then
    pyenv install 3.11.8
else
    echo "Python 3.11.8 已安装"
fi

# 设置全局 Python 版本（仅对当前用户）
echo "[7/8] 设置 Python 版本..."
pyenv global 3.11.8

# 升级 pip 和安装基础包
echo "[8/8] 安装基础 Python 包..."
python -m pip install --upgrade pip setuptools wheel virtualenv

# 验证安装
echo "=== 验证安装结果 ==="
echo "Python 版本: $(python3 --version)"
echo "pip 版本: $(pip3 --version)"
echo "virtualenv 版本: $(virtualenv --version)"

echo "=== 环境配置完成 ==="