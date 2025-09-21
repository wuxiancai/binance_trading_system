#!/bin/bash
# Ubuntu Server 24 环境配置脚本
# 用于安装系统 Python、pip、虚拟环境等必要组件

set -e  # 遇到错误立即退出

echo "=== 开始配置 Ubuntu Server 24 环境 ==="

# 更新系统包
echo "[1/4] 更新系统包..."
sudo apt update && sudo apt upgrade -y

# 安装基础工具
echo "[2/4] 安装基础工具..."
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

# 安装系统 Python 和相关工具
echo "[3/4] 安装系统 Python 和开发工具..."
sudo apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    python3-setuptools \
    python3-wheel

# 升级 pip 和安装基础包
echo "[4/4] 升级 pip 和安装基础包..."
python3 -m pip install --user --upgrade pip setuptools wheel

# 验证安装
echo "=== 验证安装结果 ==="
echo "Python 版本: $(python3 --version)"
echo "pip 版本: $(python3 -m pip --version)"
echo "venv 模块: $(python3 -c 'import venv; print("可用")')"

echo "=== 环境配置完成 ==="
echo "提示: 系统将使用 Ubuntu 24.04 自带的 Python $(python3 --version | cut -d' ' -f2) 版本"