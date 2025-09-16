import os
from dataclasses import dataclass


def str2bool(v: str | None, default: bool = False) -> bool:
    if v is None:
        return default
    return v.lower() in {"1", "true", "t", "yes", "y"}


@dataclass(frozen=True)
class Config:
    # ---------------------------
    # 应用运行级参数（通用）
    # ---------------------------
    log_level: str = "DEBUG"              # 日志等级：DEBUG/INFO/WARN/ERROR
    db_path: str = "trader.db"            # SQLite 数据库文件路径
    tz: str = "Asia/Shanghai"                       # 时区（仅用于日志/显示）

    # ---------------------------
    # 交易所与订阅参数
    # ---------------------------
    api_key: str = "00832d003a3d2f76c718ba02278363ec3be6abff352051e3c3b09ca0100b723f"                    # 币安 API Key（非干跑时必须）
    api_secret: str = "523755dec380c497f8bec63929ba16f3918a15bac06a78c6535ef65f0d5aa523"                 # 币安 API Secret
    use_testnet: bool = True              # 是否使用测试网：1/true 为测试网
    symbol: str = "ETHUSDT"              # 交易对（如 BTCUSDT）
    interval: str = "15m"               # K线周期（如 15m）
    window: int = 20                      # 布林带窗口期（默认 20）

    # ---------------------------
    # 策略与风控参数
    # ---------------------------
    stop_loss_pct: float = 0.02           # 止损百分比（0.02 表示 2%）
    max_position_pct: float = 0.1         # 单次最大仓位占可用 USDT 的比例（1.0 表示 100%）
    leverage: int = 10                    # 杠杆倍数
    only_on_close: bool = True            # 仅在 K 线收盘时触发策略信号
    stop_loss_enabled: bool = True        # 是否在开仓后自动挂止损单

    # ---------------------------
    # 指标参数（布林带）
    # ---------------------------
    boll_multiplier: float = 2.0          # 布林带倍数（默认 2.0）
    boll_ddof: int = 1                    # 标准差自由度 ddof（1 更接近币安计算方式）
    indicator_max_rows: int = 200         # 指标缓存的最大行数（用于限制内存）

    # ---------------------------
    # WebSocket 行情流参数
    # ---------------------------
    ws_ping_interval: int = 20            # WS 心跳间隔秒
    ws_ping_timeout: int = 60             # WS 心跳超时秒
    ws_backoff_initial: int = 1           # WS 重连初始回退秒
    ws_backoff_max: int = 60              # WS 重连最大回退秒

    # ---------------------------
    # 下单与网络参数
    # ---------------------------
    recv_window: int = 5000               # REST 下单 recvWindow（毫秒）
    http_timeout: int = 30                # REST HTTP 超时时间（秒）
    qty_precision: int = 3                # 数量精度（用于简单数量四舍五入/截断）
    price_round: int = 2                  # 价格保留小数位（用于止损 stopPrice 舍入）
    stop_loss_working_type: str = "CONTRACT_PRICE"  # 止损触发价格类型（MARK_PRICE/CONTRACT_PRICE）

    # ---------------------------
    # 端点配置（可用环境覆盖）
    # ---------------------------
    ws_base: str = "wss://fstream.binancefuture.com"  # 行情 WebSocket 基础地址（默认测试网 Futures Testnet 公共行情流）
    rest_base: str = "https://testnet.binancefuture.com"  # REST 下单基础地址（默认测试网）


def load_config() -> Config:
    # 单一默认来源：Config 的默认值
    defaults = Config()

    # 基础
    log_level = (os.getenv("LOG_LEVEL") or defaults.log_level).upper()
    db_path = os.getenv("DB_PATH") or defaults.db_path
    tz = os.getenv("TZ") or defaults.tz

    # 交易所与订阅
    api_key = os.getenv("BINANCE_API_KEY", defaults.api_key)
    api_secret = os.getenv("BINANCE_API_SECRET", defaults.api_secret)
    symbol = (os.getenv("SYMBOL") or defaults.symbol).upper()
    interval = os.getenv("INTERVAL") or defaults.interval
    window = int(os.getenv("WINDOW") or defaults.window)

    # 策略与风控
    stop_loss_pct = float(os.getenv("STOP_LOSS_PCT") or defaults.stop_loss_pct)
    max_position_pct = float(os.getenv("MAX_POSITION_PCT") or defaults.max_position_pct)
    leverage = int(os.getenv("LEVERAGE") or defaults.leverage)
    only_on_close = str2bool(os.getenv("ONLY_ON_CLOSE"), defaults.only_on_close)
    stop_loss_enabled = str2bool(os.getenv("STOP_LOSS_ENABLED"), defaults.stop_loss_enabled)

    # 指标参数
    boll_multiplier = float(os.getenv("BOLL_MULTIPLIER") or defaults.boll_multiplier)
    boll_ddof = int(os.getenv("BOLL_DDOF") or defaults.boll_ddof)
    indicator_max_rows = int(os.getenv("INDICATOR_MAX_ROWS") or defaults.indicator_max_rows)

    # WebSocket
    ws_ping_interval = int(os.getenv("WS_PING_INTERVAL") or defaults.ws_ping_interval)
    ws_ping_timeout = int(os.getenv("WS_PING_TIMEOUT") or defaults.ws_ping_timeout)
    ws_backoff_initial = int(os.getenv("WS_BACKOFF_INITIAL") or defaults.ws_backoff_initial)
    ws_backoff_max = int(os.getenv("WS_BACKOFF_MAX") or defaults.ws_backoff_max)

    # 下单与网络
    recv_window = int(os.getenv("RECV_WINDOW") or defaults.recv_window)
    http_timeout = int(os.getenv("HTTP_TIMEOUT") or defaults.http_timeout)
    qty_precision = int(os.getenv("QTY_PRECISION") or defaults.qty_precision)
    price_round = int(os.getenv("PRICE_ROUND") or defaults.price_round)
    stop_loss_working_type = os.getenv("STOP_LOSS_WORKING_TYPE") or defaults.stop_loss_working_type

    # 运行网络与端点
    use_testnet = str2bool(os.getenv("USE_TESTNET"), defaults.use_testnet)
    ws_base_env = os.getenv("WS_BASE")
    rest_base_env = os.getenv("REST_BASE")
    if ws_base_env:
        ws_base = ws_base_env.rstrip("/")
    else:
        ws_base = defaults.ws_base if use_testnet else "wss://fstream.binance.com"
    if rest_base_env:
        rest_base = rest_base_env.rstrip("/")
    else:
        rest_base = defaults.rest_base if use_testnet else "https://fapi.binance.com"

    return Config(
        # 基础
        log_level=log_level,
        db_path=db_path,
        tz=tz,
        # 交易所与订阅
        api_key=api_key,
        api_secret=api_secret,
        use_testnet=use_testnet,
        symbol=symbol,
        interval=interval,
        window=window,
        # 策略与风控
        stop_loss_pct=stop_loss_pct,
        max_position_pct=max_position_pct,
        leverage=leverage,
        only_on_close=only_on_close,
        stop_loss_enabled=stop_loss_enabled,
        # 指标
        boll_multiplier=boll_multiplier,
        boll_ddof=boll_ddof,
        indicator_max_rows=indicator_max_rows,
        # WebSocket
        ws_ping_interval=ws_ping_interval,
        ws_ping_timeout=ws_ping_timeout,
        ws_backoff_initial=ws_backoff_initial,
        ws_backoff_max=ws_backoff_max,
        # 下单与网络
        recv_window=recv_window,
        http_timeout=http_timeout,
        qty_precision=qty_precision,
        price_round=price_round,
        stop_loss_working_type=stop_loss_working_type,
        # 端点
        ws_base=ws_base,
        rest_base=rest_base,
    )