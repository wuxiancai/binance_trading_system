# 基于币安 API 的自动化交易系统开发文档

## 1. 项目概述

本项目旨在开发一个基于 **币安现货/永续合约 API**
的自动化交易系统。该系统部署在 **Ubuntu Server 24.04 云服务器** 上，使用
**WebSocket 实时行情** 和 **REST API 下单**，实现稳定、高效的策略执行。

目标交易对：**BTC/USDT 永续合约**\
交易所地址：[Binance Futures
BTC/USDT](https://www.binance.com/zh-CN/futures/BTCUSDT)\
API 文档：[Binance API
文档](https://developers.binance.com/docs/zh-CN/binance-spot-api-docs/websocket-api/)
币安提供了测试环境，用于开发和测试交易策略。测试环境与主网独立，不会真实交易资金。
测试环境 API 文档：[Binance Testnet
API](https://developers.binance.com/docs/zh-CN/binance-spot-api-docs/testnet/websocket-api/general-api-information)
测试环境地址：[Binance Testnet
Futures](https://testnet.binancefuture.com/futures/BTCUSDT)

------------------------------------------------------------------------

## 2. 策略逻辑说明

系统基于 **15 分钟 K 线 BOLL（布林带）指标** 进行交易：

1.  **计算指标**
    -   使用 15 分钟 K 线计算 BOLL 指标：
        -   `UP` = 中轨 + 2 × 标准差\
        -   `DN` = 中轨 - 2 × 标准差\
        -   中轨 = 20 根 K 线的均值
2.  **交易规则**
    -   当 **价格突破 UP**，然后**回落至 UP** 时 → **买入空单**\
    -   当 **价格跌破 DN**，然后**反弹至 DN** 时 →
        **卖出空单，并买入多单**\
    -   当 **价格上涨至 UP 后再次回落至 UP** → **卖出多单并买入空单**\
    -   上述逻辑循环执行，实现**区间震荡高抛低吸**。

------------------------------------------------------------------------

## 3. 技术选型

-   **语言**：Python 3.12
-   **依赖库**：
    -   `websockets`（实时行情订阅）\
    -   `pandas`（数据计算与指标）\
    -   `numpy`（数学计算）\
    -   `python-binance`（REST 下单接口）\
    -   `asyncio`（异步并发，提高反应速度）\
-   **数据库**：SQLite（保存 K 线和交易日志）\
-   **部署环境**：Ubuntu Server 24.04 LTS

------------------------------------------------------------------------

## 4. 系统架构设计

``` mermaid
flowchart TD
    A[Binance WebSocket 实时行情] --> B[数据处理模块]
    B --> C[指标计算 (BOLL)]
    C --> D[策略引擎]
    D --> E[交易执行模块 (REST API)]
    E --> F[交易日志 & 数据存储 (SQLite)]
    F --> G[监控 & 报警 (Telegram/Email)]
```

### 模块说明

1.  **数据处理模块**：通过 WebSocket 接收实时行情，存储到内存 K
    线缓存。\
2.  **指标计算模块**：基于 pandas 计算 15 分钟 K 线的布林带。\
3.  **策略引擎**：根据 UP/DN 判断交易信号。\
4.  **交易执行模块**：调用 Binance Futures 下单 API，支持市价单。\
5.  **日志 & 数据存储**：保存每次交易和指标数值，方便回测与审计。\
6.  **监控模块**：异常时通过 Telegram Bot 报警。

------------------------------------------------------------------------

## 5. 核心代码示例

### 5.1 WebSocket 实时获取 K 线数据

``` python
import asyncio
import websockets
import json

async def kline_listener():
    url = "wss://fstream.binance.com/ws/btcusdt@kline_15m"
    async with websockets.connect(url) as ws:
        while True:
            msg = await ws.recv()
            data = json.loads(msg)
            kline = data['k']
            print(f"K线数据: {kline}")

asyncio.run(kline_listener())
```

### 5.2 计算布林带

``` python
import pandas as pd
import numpy as np

def calc_boll(df, window=20):
    df['MA'] = df['close'].rolling(window).mean()
    df['STD'] = df['close'].rolling(window).std()
    df['UP'] = df['MA'] + 2 * df['STD']
    df['DN'] = df['MA'] - 2 * df['STD']
    return df
```

### 5.3 策略执行逻辑

``` python
def strategy(price, up, dn, state):
    if price > up and state != "short":
        return "open_short"
    elif price < dn and state != "long":
        return "open_long"
    elif price <= up and state == "waiting_short":
        return "confirm_short"
    elif price >= dn and state == "waiting_long":
        return "confirm_long"
    return None
```

### 5.4 下单接口

``` python
from binance.client import Client

api_key = "YOUR_API_KEY"
api_secret = "YOUR_SECRET_KEY"
client = Client(api_key, api_secret)

def place_order(symbol, side, quantity):
    try:
        order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type="MARKET",
            quantity=quantity
        )
        print(order)
    except Exception as e:
        print(f"下单失败: {e}")
```

------------------------------------------------------------------------

## 6. 部署方案

### 6.1 安装依赖

``` bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3 python3-pip sqlite3 -y

pip install websockets pandas numpy python-binance
```

### 6.2 后台运行

``` bash
nohup python3 main.py > trader.log 2>&1 &
```

### 6.3 系统监控

-   使用 `htop` 监控 CPU/内存\
-   使用 `systemd` 配置自启动服务\
-   使用 `Telegram Bot` 接收交易通知

------------------------------------------------------------------------

## 7. 风险控制

-   **最大仓位限制**：不超过总资金 10%\
-   **强制止损**：每单最大亏损 2%\
-   **API Key 权限**：仅开启交易权限，不开启提现\
-   **异常保护**：网络断开时暂停交易，重连后恢复

------------------------------------------------------------------------

## 8. 后续扩展

-   增加多交易对支持（ETH/USDT, BNB/USDT 等）\
-   引入 **回测模块**，对历史数据进行验证\
-   接入 **Prometheus + Grafana** 进行可视化监控\
-   支持 **Docker 一键部署**

------------------------------------------------------------------------

## 9. 总结

本方案设计了一个高效、稳定的自动化交易系统，基于 **币安 Futures
API**，结合
**布林带策略**，实现高频实时监控与自动下单。系统模块化设计，支持扩展与运维，适合在
**Ubuntu Server 24.04** 上长期运行。
