import asyncio
import logging
import os
import time
from datetime import datetime
import json
import urllib.request

import pytz

from config import load_config
from db import DB
from ws_client import WSClient, KlineEvent
from indicators import Indicator
from strategy import StrategyState, decide
from trader import Trader
from webapp import start_web_server  # 新增


def _load_env_file(path: str = ".env") -> None:
    """Lightweight .env loader without external deps.
    - Lines starting with '#' are ignored
    - Supports KEY=VALUE with optional surrounding quotes
    - Doesn't overwrite existing environment variables
    """
    try:
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip()
                # strip inline comments that are preceded by whitespace
                if " #" in v:
                    v = v.split(" #", 1)[0].rstrip()
                # remove surrounding quotes if present
                if (v.startswith("\"") and v.endswith("\"")) or (v.startswith("'") and v.endswith("'")):
                    v = v[1:-1]
                # do not override pre-set env vars
                if k and (k not in os.environ):
                    os.environ[k] = v
    except Exception:
        # fail silently; fall back to defaults/env
        pass


def _interval_to_ms(interval: str) -> int:
    try:
        num = int(interval[:-1])
        unit = interval[-1]
        if unit == 'm':
            return num * 60_000
        if unit == 'h':
            return num * 60 * 60_000
        if unit == 'd':
            return num * 24 * 60 * 60_000
        return num  # already ms
    except Exception:
        return 15 * 60_000


def _fetch_recent_klines_rest(rest_base: str, symbol: str, interval: str, limit: int = 300):
    url = f"{rest_base.rstrip('/')}/fapi/v1/klines?symbol={symbol.upper()}&interval={interval}&limit={limit}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            if resp.status != 200:
                return []
            data = json.loads(resp.read().decode('utf-8'))
            now_ms = int(time.time() * 1000)
            interval_ms = _interval_to_ms(interval)
            out = []
            for it in data:
                ot = int(it[0])
                ct = int(it[6]) if len(it) > 6 else (ot + interval_ms - 1)
                is_closed = now_ms >= ct
                out.append(KlineEvent(
                    open_time=ot,
                    close_time=ct,
                    open=float(it[1]),
                    high=float(it[2]),
                    low=float(it[3]),
                    close=float(it[4]),
                    volume=float(it[5]),
                    is_closed=is_closed
                ))
            return out
    except Exception:
        return []


async def _backfill_recent_closed_klines(db: DB, cfg) -> int:
    """从REST拉取最近一段K线，补齐DB缺失记录；返回写入条数"""
    klines = _fetch_recent_klines_rest(cfg.rest_base, cfg.symbol, cfg.interval, limit=300)
    if not klines:
        return 0
    written = 0
    for k in klines:
        try:
            await db.insert_kline(k)
            written += 1
        except Exception:
            continue
    logging.info(f"REST回补K线完成，共写入 {written} 条（含覆盖）")
    return written


async def main():
    # Ensure .env variables are loaded before reading config
    _load_env_file()

    cfg = load_config()

    # logging - 配置为 UTC+8 时区
    import logging.handlers
    
    # 创建自定义的时间格式化器，使用 UTC+8 时区
    class UTC8Formatter(logging.Formatter):
        def formatTime(self, record, datefmt=None):
            # 使用 UTC+8 时区格式化时间
            dt = datetime.fromtimestamp(record.created, tz=pytz.timezone('Asia/Shanghai'))
            if datefmt:
                return dt.strftime(datefmt)
            else:
                return dt.strftime('%Y-%m-%d %H:%M:%S')
    
    # 配置日志格式
    formatter = UTC8Formatter("%(asctime)s %(levelname)s %(message)s")
    
    # 获取根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, cfg.log_level, logging.INFO))
    
    # 清除现有的处理器
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # 添加控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    logging.info(f"Starting with config: symbol={cfg.symbol}, interval={cfg.interval}")

    # tz
    tz = pytz.timezone(cfg.tz)

    # db
    db = DB(cfg.db_path)
    await db.init()

    # 回补缺失的已收盘K线（最近300根）
    try:
        await _backfill_recent_closed_klines(db, cfg)
    except Exception as e:
        logging.warning(f"回补K线失败: {e}")

    # trader
    trader = Trader(cfg.api_key, cfg.api_secret, cfg.rest_base,
                     recv_window=cfg.recv_window,
                     http_timeout=cfg.http_timeout,
                     qty_precision=cfg.qty_precision,
                     price_round=cfg.price_round,
                     stop_loss_working_type=cfg.stop_loss_working_type)
    if cfg.api_key and cfg.api_secret:
        trader.apply_leverage(cfg.symbol, cfg.leverage)

    # 启动 Web 仪表盘（后台线程，不阻塞），并注入 trader
    try:
        web_port = start_web_server(cfg, trader)
        logging.info(f"Web dashboard started at http://0.0.0.0:{web_port}/")
    except Exception as e:
        logging.warning(f"Web dashboard start failed: {e}")

    # indicator
    ind = Indicator(window=cfg.window, boll_multiplier=cfg.boll_multiplier, boll_ddof=cfg.boll_ddof, max_rows=cfg.indicator_max_rows)
    
    # 从数据库加载历史K线数据到indicators，并回填指标到数据库（仅已收盘K线）
    historical_klines = await db.get_recent_klines(cfg.window + 50)  # 多加载一些数据确保足够
    backfill_cnt = 0
    for kline_data in historical_klines:
        # 创建KlineEvent对象（历史数据均视为已收盘）
        k = KlineEvent(
            open_time=kline_data[0],
            close_time=kline_data[1], 
            open=kline_data[2],
            high=kline_data[3],
            low=kline_data[4],
            close=kline_data[5],
            volume=kline_data[6],
            is_closed=True
        )
        ma, std, up, dn = ind.add_kline(k)
        if ma is not None:
            # 回填该已收盘K线的指标
            await db.upsert_indicator(k.open_time, ma, std, up, dn)
            backfill_cnt += 1
    logging.info(f"Loaded {len(historical_klines)} historical klines into indicators, backfilled {backfill_cnt} indicators")

    # ws
    ws = WSClient(cfg.ws_base, cfg.symbol, cfg.interval,
                  ping_interval=cfg.ws_ping_interval,
                  ping_timeout=cfg.ws_ping_timeout,
                  backoff_initial=cfg.ws_backoff_initial,
                  backoff_max=cfg.ws_backoff_max,
                  open_timeout=getattr(cfg, 'ws_open_timeout', 20))

    state = StrategyState()
    # 从数据库加载最新的策略状态
    latest_state = await db.load_latest_strategy_state()
    state.load_from_dict(latest_state)
    logging.info(f"Loaded strategy state: position={state.position}, pending={state.pending}, entry_price={state.entry_price}")

    async def on_kline(k: KlineEvent):
        # persist kline
        await db.insert_kline(k)
        ma, std, up, dn = ind.add_kline(k)
        # 仅在K线收盘时写入指标，并以该已收盘K线的open_time入库，保证与交易所时间同步
        if k.is_closed and (ma is not None):
            await db.upsert_indicator(k.open_time, ma, std, up, dn)

        # 计算"实时BOLL"：最近 window-1 根已收盘 + 当前形成中的最新价(k.close)
        rt_ma, rt_std, rt_up, rt_dn = ind.compute_realtime_boll(k.close)

        # 检查是否有足够的K线数据（至少支持实时BOLL计算）才执行交易
        if rt_up is None or rt_dn is None:
            logging.info(f"等待更多K线数据以计算实时BOLL… 当前: {len(ind.df)} 行, 已收盘: {len(ind.df[ind.df['is_closed']==True])} 行")
            return

        # 添加调试信息：每10根K线输出一次BOLL值和价格对比
        if len(ind.df) % 10 == 0 or not k.is_closed:
            logging.info(f"📊 BOLL调试 - 价格: {k.close:.2f}, UP: {rt_up:.2f}, DN: {rt_dn:.2f}, 状态: {state.position}, 等待: {state.pending}")

        # 不再提前返回，而是将only_on_close/is_closed传入策略，由策略决定是否产生交易信号；
        # 这样在未收盘时也能更新pending/突破状态并保存，供仪表盘展示
        price = k.close

        # 在非模拟模式下从币安API获取实际仓位，确保交易决策基于真实仓位
        if (not cfg.simulate_trading) and cfg.api_key and cfg.api_secret:
            try:
                actual_position = trader.get_position_info(cfg.symbol)
                if actual_position is not None:
                    # 有仓位，更新本地状态
                    state.position = actual_position["position_side"]
                else:
                    # 无仓位
                    state.position = "flat"
            except Exception as e:
                logging.warning(f"获取仓位信息失败: {e}")
                # 继续执行策略逻辑，使用本地状态

        # 确保布林带指标有效才进行策略决策
        if rt_up is not None and rt_dn is not None:
            signal = decide(price, rt_up, rt_dn, state,
                             high_price=k.high, low_price=k.low,
                             is_closed=k.is_closed, only_on_close=cfg.only_on_close,
                             use_breakout_level_for_entry=getattr(cfg, 'use_breakout_level_for_entry', False),
                             reentry_buffer_pct=getattr(cfg, 'reentry_buffer_pct', 0.0))
            if signal:
                await db.log_signal(int(time.time()*1000), signal, price)
                logging.info(f"Signal: {signal} @ {price} (RT_UP={rt_up:.2f}, RT_DN={rt_dn:.2f})")

                # 模拟交易模式：只记录交易信号，不执行真实交易
                if cfg.simulate_trading:
                    logging.info(f"模拟交易模式 - 信号: {signal} @ {price}")
                    try:
                        if signal == "open_short":
                            qty = cfg.simulate_balance * cfg.max_position_pct / price  # 模拟计算数量
                            await db.log_trade(int(time.time()*1000), "SELL", qty, price, "SIMULATED", "FILLED")
                            logging.info(f"模拟开空仓: {qty:.3f} @ {price}")
                        elif signal == "open_long":
                            qty = cfg.simulate_balance * cfg.max_position_pct / price  # 模拟计算数量
                            await db.log_trade(int(time.time()*1000), "BUY", qty, price, "SIMULATED", "FILLED")
                            logging.info(f"模拟开多仓: {qty:.3f} @ {price}")
                        elif signal == "close_short_open_long":
                            # 模拟平空仓+开多仓
                            await db.log_trade(int(time.time()*1000), "BUY_CLOSE", 0, price, "SIMULATED", "FILLED")
                            await db.update_trade_status_on_close("BUY_CLOSE")
                            qty = cfg.simulate_balance * cfg.max_position_pct / price
                            await db.log_trade(int(time.time()*1000), "BUY_OPEN", qty, price, "SIMULATED", "FILLED")
                            logging.info(f"模拟平空开多: {qty:.3f} @ {price}")
                        elif signal == "close_long_open_short":
                            # 模拟平多仓+开空仓
                            await db.log_trade(int(time.time()*1000), "SELL_CLOSE", 0, price, "SIMULATED", "FILLED")
                            await db.update_trade_status_on_close("SELL_CLOSE")
                            qty = cfg.simulate_balance * cfg.max_position_pct / price
                            await db.log_trade(int(time.time()*1000), "SELL_OPEN", qty, price, "SIMULATED", "FILLED")
                            logging.info(f"模拟平空开空: {qty:.3f} @ {price}")
                        elif signal == "stop_loss_short":
                            # 模拟空仓止损
                            await db.log_trade(int(time.time()*1000), "BUY_STOP_LOSS", 0, price, "SIMULATED", "FILLED")
                            await db.update_trade_status_on_close("BUY_STOP_LOSS")
                            logging.info(f"模拟空仓止损 @ {price}")
                        elif signal == "stop_loss_long":
                            # 模拟多仓止损
                            await db.log_trade(int(time.time()*1000), "SELL_STOP_LOSS", 0, price, "SIMULATED", "FILLED")
                            await db.update_trade_status_on_close("SELL_STOP_LOSS")
                            logging.info(f"模拟多仓止损 @ {price}")
                    except Exception as e:
                        logging.error(f"模拟交易记录失败: {e}")
                    return

                if not (cfg.api_key and cfg.api_secret):
                    return

                # 真实交易模式
                try:
                    if signal == "open_short":
                        qty = trader.calc_qty(cfg.symbol, price, cfg.max_position_pct)
                        if qty > 0:
                            order = trader.place_market(cfg.symbol, side="SELL", qty=qty)
                            await db.log_trade(int(time.time()*1000), "SELL", qty, price, str(order.get("orderId")), order.get("status"))
                            # state已在strategy.py中更新
                            if cfg.stop_loss_enabled:
                                trader.place_stop_loss(cfg.symbol, position="short", entry_price=price, stop_loss_pct=cfg.stop_loss_pct)
                    elif signal == "open_long":
                        qty = trader.calc_qty(cfg.symbol, price, cfg.max_position_pct)
                        if qty > 0:
                            order = trader.place_market(cfg.symbol, side="BUY", qty=qty)
                            await db.log_trade(int(time.time()*1000), "BUY", qty, price, str(order.get("orderId")), order.get("status"))
                            # state已在strategy.py中更新
                            if cfg.stop_loss_enabled:
                                trader.place_stop_loss(cfg.symbol, position="long", entry_price=price, stop_loss_pct=cfg.stop_loss_pct)
                    elif signal == "close_short_open_long":
                        # 平空仓+开多仓
                        # Close all short position using market close all
                        close = trader.close_all_position(cfg.symbol)
                        if close:
                            await db.log_trade(int(time.time()*1000), "BUY_CLOSE", 0, price, str(close.get("orderId")), close.get("status"))
                            await db.update_trade_status_on_close("BUY_CLOSE")
                            qty = trader.calc_qty(cfg.symbol, price, cfg.max_position_pct)
                            if qty > 0:
                                open_ = trader.place_market(cfg.symbol, side="BUY", qty=qty)
                                await db.log_trade(int(time.time()*1000), "BUY_OPEN", qty, price, str(open_.get("orderId")), open_.get("status"))
                                # state已在strategy.py中更新
                                if cfg.stop_loss_enabled:
                                    trader.place_stop_loss(cfg.symbol, position="long", entry_price=price, stop_loss_pct=cfg.stop_loss_pct)
                    elif signal == "close_long_open_short":
                        # 平多仓+开空仓
                        # Close all long position using market close all
                        close = trader.close_all_position(cfg.symbol)
                        if close:
                            await db.log_trade(int(time.time()*1000), "SELL_CLOSE", 0, price, str(close.get("orderId")), close.get("status"))
                            await db.update_trade_status_on_close("SELL_CLOSE")
                            qty = trader.calc_qty(cfg.symbol, price, cfg.max_position_pct)
                            if qty > 0:
                                open_ = trader.place_market(cfg.symbol, side="SELL", qty=qty)
                                await db.log_trade(int(time.time()*1000), "SELL_OPEN", qty, price, str(open_.get("orderId")), open_.get("status"))
                                # state已在strategy.py中更新
                                if cfg.stop_loss_enabled:
                                    trader.place_stop_loss(cfg.symbol, position="short", entry_price=price, stop_loss_pct=cfg.stop_loss_pct)
                    elif signal == "stop_loss_short":
                        # 空仓止损
                        # Close all short position using market close all
                        order = trader.close_all_position(cfg.symbol)
                        if order:
                            await db.log_trade(int(time.time()*1000), "BUY_STOP_LOSS", 0, price, str(order.get("orderId")), order.get("status"))
                            await db.update_trade_status_on_close("BUY_STOP_LOSS")
                            # state已在strategy.py中更新为flat
                    elif signal == "stop_loss_long":
                        # 多仓止损
                        # Close all long position using market close all
                        order = trader.close_all_position(cfg.symbol)
                        if order:
                            await db.log_trade(int(time.time()*1000), "SELL_STOP_LOSS", 0, price, str(order.get("orderId")), order.get("status"))
                            await db.update_trade_status_on_close("SELL_STOP_LOSS")
                            # state已在strategy.py中更新为flat
                except Exception as e:
                    logging.error(f"order failed: {e}")
                    await db.log_error(int(time.time()*1000), "order", str(e))
        else:
            logging.debug(f"实时BOLL未就绪，跳过策略决策 (RT_UP={rt_up}, RT_DN={rt_dn})")
        
        # 保存策略状态
        await db.save_strategy_state(
            int(time.time()*1000), 
            state.position, 
            state.pending, 
            state.entry_price, 
            state.breakout_level,
            state.breakout_up,
            state.breakout_dn,
            state.last_close_price
        )

    await ws.connect_and_listen(on_kline)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass