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

系统支持通过环境变量覆盖默认配置。有两种方式设置环境变量：

#### 方式一：使用 .env 文件（推荐）

部署完成后，创建并编辑配置文件：

```bash
# 复制示例配置文件
cp $HOME/binance_trading_system/.env.example $HOME/binance_trading_system/.env

# 编辑配置文件
nano $HOME/binance_trading_system/.env
```

然后在启动前加载环境变量：

```bash
# 加载 .env 文件中的环境变量
cd $HOME/binance_trading_system
export $(grep -v '^#' .env | xargs)

# 启动系统
python main.py
```

#### 方式二：直接设置环境变量

```bash
# 设置环境变量
export USE_TESTNET=1
export SYMBOL=BTCUSDT
export INTERVAL=15m

# 启动系统
python main.py
```

#### 重要配置项说明

##### 🔧 基础应用参数
```bash
LOG_LEVEL=DEBUG           # 日志等级：DEBUG/INFO/WARNING/ERROR
DB_PATH=trader.db         # SQLite 数据库文件路径
TZ=Asia/Shanghai          # 时区设置（用于日志显示）
```

##### 🔑 交易所配置
```bash
# API 配置（真实交易时必须配置）
BINANCE_API_KEY=your_api_key_here      # 币安 API Key
BINANCE_API_SECRET=your_api_secret_here # 币安 API Secret
USE_TESTNET=1             # 1=测试网，0=主网
SYMBOL=BTCUSDT            # 交易对
INTERVAL=15m              # K线周期（1m/5m/15m/1h/4h/1d等）
WINDOW=20                 # 布林带窗口期
```

##### 📊 策略与风控参数
```bash
STOP_LOSS_PCT=0.02        # 止损比例（0.02 = 2%）
MAX_POSITION_PCT=1.0      # 最大仓位比例（1.0 = 100%）
LEVERAGE=10               # 杠杆倍数
ONLY_ON_CLOSE=1           # 仅在K线收盘时处理信号（1=是，0=否）
STOP_LOSS_ENABLED=1       # 开仓后自动挂止损单（1=是，0=否）
```

##### 📈 技术指标参数
```bash
BOLL_MULTIPLIER=2.0       # 布林带倍数
BOLL_DDOF=0               # 标准差自由度
INDICATOR_MAX_ROWS=200    # 指标缓存最大行数
```

##### 🌐 网络与连接参数
```bash
WS_PING_INTERVAL=20       # WebSocket 心跳间隔（秒）
WS_PING_TIMEOUT=60        # WebSocket 心跳超时（秒）
WS_BACKOFF_INITIAL=1      # 重连初始退避时间（秒）
WS_BACKOFF_MAX=60         # 重连最大退避时间（秒）
RECV_WINDOW=5000          # REST API 接收窗口（毫秒）
HTTP_TIMEOUT=30           # HTTP 请求超时（秒）
```

##### 🎯 交易精度参数
```bash
QTY_PRECISION=3           # 数量精度（小数位数）
PRICE_ROUND=2             # 价格保留小数位
STOP_LOSS_WORKING_TYPE=CONTRACT_PRICE  # 止损触发价格类型
```

##### 🔗 端点配置（高级用户）
```bash
# 通常无需修改，系统会根据 USE_TESTNET 自动选择
REST_BASE=                # REST API 基础地址（留空使用默认）
WS_BASE=                  # WebSocket 基础地址（留空使用默认）
```

#### 配置示例

##### 开发测试配置
```bash
# 测试网 + 模拟交易
USE_TESTNET=1
SYMBOL=BTCUSDT
INTERVAL=15m
WINDOW=20
STOP_LOSS_PCT=0.02
MAX_POSITION_PCT=1.0
LEVERAGE=10
ONLY_ON_CLOSE=1
STOP_LOSS_ENABLED=1
LOG_LEVEL=DEBUG
```

##### 生产环境配置
```bash
# 主网 + 真实交易（请确保 API Key 权限正确）
USE_TESTNET=0
BINANCE_API_KEY=your_mainnet_api_key
BINANCE_API_SECRET=your_mainnet_api_secret
SYMBOL=BTCUSDT
INTERVAL=15m
LEVERAGE=10
STOP_LOSS_PCT=0.015
MAX_POSITION_PCT=1.0
LOG_LEVEL=DEBUG
TZ=Asia/Shanghai
```

#### 配置优先级

系统按以下优先级加载配置：
1. **环境变量**（最高优先级）
2. **代码中的默认值**（最低优先级）

这意味着环境变量会覆盖代码中的默认配置。

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

### 服务环境变量配置

systemd 服务会自动读取项目目录下的 `.env` 文件。如需修改配置：

#### 方法一：修改 .env 文件（推荐）

```bash
# 编辑环境变量文件
nano $HOME/binance_trading_system/.env

# 重启服务使配置生效
sudo systemctl restart binance_trading_system
```

#### 方法二：修改 systemd 服务文件

```bash
# 编辑服务文件
sudo systemctl edit binance_trading_system

# 在编辑器中添加环境变量
[Service]
Environment="USE_TESTNET=0"
Environment="SYMBOL=ETHUSDT"
Environment="INTERVAL=5m"

# 重新加载并重启服务
sudo systemctl daemon-reload
sudo systemctl restart binance_trading_system
```

#### 查看服务环境变量

```bash
# 查看服务的环境变量
sudo systemctl show binance_trading_system --property=Environment

# 查看服务配置
sudo systemctl cat binance_trading_system
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

4. **环境变量配置问题**
   ```bash
   # 检查 .env 文件是否存在
   ls -la $HOME/binance_trading_system/.env
   
   # 检查环境变量格式（不应有空格）
   cat $HOME/binance_trading_system/.env | grep -E "^[A-Z_]+=.*"
   
   # 测试环境变量加载
   cd $HOME/binance_trading_system
   export $(grep -v '^#' .env | xargs)
   echo $USE_TESTNET
   
   # 验证配置是否正确
   python -c "from config import load_config; print(load_config())"
   ```

5. **API 连接问题**
   ```bash
   # 检查网络连接
   curl -I https://testnet.binancefuture.com/fapi/v1/ping
   
   # 检查 API 密钥配置
   grep "BINANCE_API" $HOME/binance_trading_system/.env
   
   # 测试 API 连接
   cd $HOME/binance_trading_system && source .venv/bin/activate
   python -c "
   import os
   from config import load_config
   config = load_config()
   print(f'使用测试网: {config.use_testnet}')
   print(f'API Key: {config.api_key[:10]}...')
   print(f'REST 端点: {config.rest_base}')
   "
   ```

6. **Python 依赖问题**
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

# 恢复数据和配置
cp /tmp/trader.db $HOME/binance_trading_system/
cp /tmp/.env $HOME/binance_trading_system/

# 重新加载环境变量并重启服务
cd $HOME/binance_trading_system
export $(grep -v '^#' .env | xargs)
sudo systemctl restart binance_trading_system
```

### 配置文件管理

#### 备份配置
```bash
# 创建配置备份
mkdir -p ~/backups
cp $HOME/binance_trading_system/.env ~/backups/.env.$(date +%Y%m%d_%H%M%S)

# 备份数据库
cp $HOME/binance_trading_system/trader.db ~/backups/trader.db.$(date +%Y%m%d_%H%M%S)
```

#### 恢复配置
```bash
# 恢复环境变量配置
cp ~/backups/.env.20240101_120000 $HOME/binance_trading_system/.env

# 重新加载配置
cd $HOME/binance_trading_system
export $(grep -v '^#' .env | xargs)

# 重启服务
sudo systemctl restart binance_trading_system
```

#### 配置验证
```bash
# 验证配置文件语法
cd $HOME/binance_trading_system
python -c "
try:
    from config import load_config
    config = load_config()
    print('✅ 配置加载成功')
    print(f'交易对: {config.symbol}')
    print(f'测试网: {config.use_testnet}')
    print(f'杠杆: {config.leverage}')
except Exception as e:
    print(f'❌ 配置错误: {e}')
"
```

## 📞 技术支持

如遇到部署问题，请检查：

1. 系统版本是否为 Ubuntu 24.04
2. 用户是否具有 sudo 权限
3. 网络连接是否正常
4. 磁盘空间是否充足

---

**注意**: 本系统涉及金融交易，请在充分测试后再用于生产环境。建议先在测试网环境下验证所有功能。