#!/bin/bash
# 币安交易系统一键自动化部署脚本
# 适用于 Ubuntu Server 24.04 LTS
# 作者: AI Assistant
# 版本: 1.0

set -e  # 遇到错误立即退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 配置变量
PROJECT_NAME="binance_trading_system"
DEPLOY_USER="$(whoami)"
DEPLOY_DIR="$HOME/${PROJECT_NAME}"
SERVICE_NAME="${PROJECT_NAME}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查是否为 root 用户
check_root() {
    if [[ $EUID -eq 0 ]]; then
        log_error "请不要使用 root 用户运行此脚本"
        log_info "请使用具有 sudo 权限的普通用户运行"
        exit 1
    fi
}

# 检查 sudo 权限
check_sudo() {
    if ! sudo -n true 2>/dev/null; then
        log_info "需要 sudo 权限，请输入密码"
        sudo -v
    fi
}

# 检查系统版本
check_system() {
    if [[ ! -f /etc/os-release ]]; then
        log_error "无法检测系统版本"
        exit 1
    fi
    
    source /etc/os-release
    if [[ "$ID" != "ubuntu" ]] || [[ "$VERSION_ID" != "24.04" ]]; then
        log_warning "此脚本专为 Ubuntu 24.04 设计，当前系统: $PRETTY_NAME"
        read -p "是否继续？(y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
}

# 显示部署信息
show_deploy_info() {
    echo
    echo "======================================"
    echo "    币安交易系统自动化部署脚本"
    echo "======================================"
    echo "项目名称: $PROJECT_NAME"
    echo "部署目录: $DEPLOY_DIR"
    echo "运行用户: $DEPLOY_USER"
    echo "服务名称: $SERVICE_NAME"
    echo "脚本目录: $SCRIPT_DIR"
    echo "项目根目录: $PROJECT_ROOT"
    echo "======================================"
    echo
}

# 执行部署步骤
execute_step() {
    local step_name="$1"
    local script_path="$2"
    
    log_info "执行步骤: $step_name"
    
    if [[ ! -f "$script_path" ]]; then
        log_error "脚本文件不存在: $script_path"
        exit 1
    fi
    
    chmod +x "$script_path"
    if bash "$script_path"; then
        log_success "步骤完成: $step_name"
    else
        log_error "步骤失败: $step_name"
        exit 1
    fi
    echo
}

# 复制项目文件
copy_project_files() {
    log_info "复制项目文件到部署目录..."
    
    # 确保部署目录存在
    mkdir -p "$DEPLOY_DIR"
    
    # 复制项目文件（排除不必要的文件）
    rsync -av \
        --exclude='.git' \
        --exclude='.venv' \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        --exclude='.env' \
        --exclude='trader.db' \
        --exclude='run.log' \
        --exclude='app.pid' \
        "$PROJECT_ROOT/" "$DEPLOY_DIR/"
    
    log_success "项目文件复制完成"
}

# 配置防火墙
setup_firewall() {
    log_info "配置防火墙..."
    
    if command -v ufw >/dev/null 2>&1; then
        sudo ufw allow 5000/tcp comment "Binance Trading System Web Interface"
        log_success "防火墙规则已添加 (端口 5000)"
    else
        log_warning "未检测到 ufw，请手动配置防火墙开放端口 5000"
    fi
}

# 主函数
main() {
    # 前置检查
    check_root
    check_sudo
    check_system
    
    # 显示部署信息
    show_deploy_info
    
    echo
    log_info "开始自动化部署..."
    echo
    
    # 执行部署步骤
    execute_step "环境配置" "$SCRIPT_DIR/setup_environment.sh"
    
    # 重新加载环境变量以使用 pyenv
    log_info "重新加载 Python 环境"
    export PYENV_ROOT="$HOME/.pyenv"
    export PATH="$PYENV_ROOT/bin:$PATH"
    if command -v pyenv >/dev/null 2>&1; then
        eval "$(pyenv init -)"
        log_success "pyenv 环境已加载"
    else
        log_warning "pyenv 未找到，请重新登录后再次运行部署脚本"
        log_info "或者手动执行: source ~/.bashrc 或 source ~/.zshrc"
    fi
    echo
    
    execute_step "项目部署" "$SCRIPT_DIR/deploy_project.sh"
    
    # 复制项目文件
    copy_project_files
    echo
    
    execute_step "服务配置" "$SCRIPT_DIR/setup_service.sh"
    
    # 配置防火墙
    setup_firewall
    echo
    
    # 部署完成
    log_success "=== 自动化部署完成 ==="
    echo
    echo "下一步操作:"
    echo "1. 编辑配置文件: sudo nano $DEPLOY_DIR/.env"
    echo "2. 启动服务: sudo systemctl start $SERVICE_NAME"
    echo "3. 查看状态: sudo systemctl status $SERVICE_NAME"
    echo "4. 查看日志: sudo journalctl -u $SERVICE_NAME -f"
    echo "5. 访问 Web 界面: http://服务器IP:5000"
    echo
    echo "重要提醒:"
    echo "- 请务必修改 .env 文件中的 API 密钥等敏感信息"
    echo "- 建议先在测试网环境下验证系统功能"
    echo "- 生产环境请配置真实 API 密钥并设置 USE_TESTNET=0"
    echo
}

# 脚本入口
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi