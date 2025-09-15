# 币安交易系统 Ubuntu Server 24 自动化部署指南

本目录包含了在 Ubuntu Server 24.04 LTS 上自动化部署币安交易系统的完整脚本集合。

## 📁 文件说明

- `auto_deploy.sh` - 一键自动化部署主脚本
- `setup_environment.sh` - 系统环境配置脚本
- `deploy_project.sh` - 项目部署脚本
- `setup_service.sh` - systemd 服务配置脚本
- `README.md` - 本说明文档

## 🚀 快速部署

### 前置要求

1. **操作系统**: Ubuntu Server 24.04 LTS
2. **用户权限**: 具有 sudo 权限的普通用户（非 root）
3. **网络连接**: 能够访问互联网下载软件包
4. **硬件要求**: 
   - CPU: 1核心以上
   - 内存: 2GB 以上
   - 存储: 10GB 以上可用空间
5. **注意**: 系统将使用 pyenv 管理 Python 版本，避免与系统 Python 冲突

### 一键部署

```bash
# 1. 上传项目文件到服务器
scp -r binance_trading_system/ user@server_ip:/tmp/

# 2. 登录服务器
ssh user@server_ip

# 3. 进入项目目录
cd /tmp/binance_trading_system

# 4. 执行一键部署脚本
chmod +x deploy/auto_deploy.sh
./deploy/auto_deploy.sh
```

## 📋 部署步骤详解

### 步骤 1: 环境配置
- 更新系统软件包
- 安装 pyenv（Python 版本管理器）
- 通过 pyenv 安装 Python 3.11.8（独立于系统 Python）
- 配置虚拟环境
- **优势**: 避免与系统 Python 版本冲突，支持多版本 Python 管理

### 步骤 2: 项目部署
- 使用当前用户运行服务
- 创建部署目录 `$HOME/binance_trading_system`
- 安装 Python 依赖包
- 配置项目文件和权限

### 步骤 3: 服务配置
- 创建 systemd 服务文件
- 配置开机自启动
- 设置日志和安全策略

### 步骤 4: 防火墙配置
- 开放 Web 界面端口 (5000)

## ⚙️ 配置说明

### Python 环境说明

#### pyenv 使用

部署脚本使用 pyenv 管理 Python 版本：

```bash
# 查看已安装的 Python 版本
pyenv versions

# 查看当前使用的 Python 版本
pyenv version

# 切换 Python 版本（如需要）
pyenv global 3.11.8

# 查看 Python 路径
which python
```

#### 虚拟环境

项目使用独立的虚拟环境，位于 `$HOME/binance_trading_system/.venv`：

```bash
# 激活虚拟环境
source $HOME/binance_trading_system/.venv/bin/activate

# 查看虚拟环境中的包
pip list

# 退出虚拟环境
deactivate
```

### 环境变量配置

部署完成后，需要编辑配置文件：

```bash
nano $HOME/binance_trading_system/.env
```

重要配置项：

```bash
# 运行模式
DRY_RUN=1                    # 1=模拟交易，0=真实交易
USE_TESTNET=1               # 1=测试网，0=主网

# API 配置（真实交易时必须配置）
BINANCE_API_KEY=your_api_key_here
BINANCE_API_SECRET=your_api_secret_here

# 交易配置
SYMBOL=BTCUSDT             # 交易对
INTERVAL=15m               # K线周期
LEVERAGE=5                 # 杠杆倍数
STOP_LOSS_PCT=0.02         # 止损比例
MAX_POSITION_PCT=0.10      # 最大仓位比例
```

## 🔧 服务管理

### 常用命令

```bash
# 启动服务
sudo systemctl start binance_trading_system

# 停止服务
sudo systemctl stop binance_trading_system

# 重启服务
sudo systemctl restart binance_trading_system

# 查看服务状态
sudo systemctl status binance_trading_system

# 查看实时日志
sudo journalctl -u binance_trading_system -f

# 查看历史日志
sudo journalctl -u binance_trading_system --since "1 hour ago"

# 禁用开机自启
sudo systemctl disable binance_trading_system

# 启用开机自启
sudo systemctl enable binance_trading_system
```

### 服务状态检查

```bash
# 检查服务是否运行
sudo systemctl is-active binance_trading_system

# 检查是否开机自启
sudo systemctl is-enabled binance_trading_system

# 查看端口占用
sudo netstat -tlnp | grep :5000
```

## 🌐 Web 界面访问

部署完成后，可通过以下方式访问 Web 管理界面：

```
http://服务器IP:5000
```

## 📊 监控和维护

### 日志文件位置

- **系统日志**: `sudo journalctl -u binance_trading_system`
- **应用日志**: `$HOME/binance_trading_system/run.log`
- **数据库**: `$HOME/binance_trading_system/trader.db`

### 性能监控

```bash
# 查看进程资源使用
top -p $(pgrep -f "python.*main.py")

# 查看内存使用
ps aux | grep "python.*main.py"

# 查看磁盘使用
du -sh $HOME/binance_trading_system/
```

### 数据备份

```bash
# 备份数据库
cp $HOME/binance_trading_system/trader.db /backup/trader_$(date +%Y%m%d_%H%M%S).db

# 备份配置文件
cp $HOME/binance_trading_system/.env /backup/env_$(date +%Y%m%d_%H%M%S).backup
```

## 🔒 安全建议

1. **API 密钥安全**
   - 使用专门的交易 API 密钥
   - 限制 API 权限（仅交易权限）
   - 定期轮换 API 密钥

2. **服务器安全**
   - 配置防火墙，仅开放必要端口
   - 使用 SSH 密钥认证
   - 定期更新系统补丁

3. **网络安全**
   - 考虑使用 HTTPS（配置反向代理）
   - 限制 Web 界面访问 IP

## 🐛 故障排除

### 常见问题

1. **服务启动失败**
   ```bash
   # 查看详细错误信息
   sudo journalctl -u binance_trading_system --no-pager
   ```

2. **端口被占用**
   ```bash
   # 查看端口占用
   sudo lsof -i :5000
   # 杀死占用进程
   sudo kill -9 <PID>
   ```

3. **权限问题**
   ```bash
   # 重新设置文件权限
   chmod -R u+rw $HOME/binance_trading_system
   ```

4. **Python 依赖问题**
   ```bash
   # 重新安装依赖
   cd $HOME/binance_trading_system && source .venv/bin/activate && pip install -r requirements.txt
   ```

### 重新部署

如果需要重新部署：

```bash
# 停止服务
sudo systemctl stop binance_trading_system

# 备份数据
cp $HOME/binance_trading_system/trader.db /tmp/
cp $HOME/binance_trading_system/.env /tmp/

# 删除旧部署
rm -rf $HOME/binance_trading_system

# 重新执行部署脚本
./deploy/auto_deploy.sh

# 恢复数据
cp /tmp/trader.db $HOME/binance_trading_system/
cp /tmp/.env $HOME/binance_trading_system/
```

## 📞 技术支持

如遇到部署问题，请检查：

1. 系统版本是否为 Ubuntu 24.04
2. 用户是否具有 sudo 权限
3. 网络连接是否正常
4. 磁盘空间是否充足

---

**注意**: 本系统涉及金融交易，请在充分测试后再用于生产环境。建议先在测试网环境下验证所有功能。