import asyncio
import logging
import os
import time
from datetime import datetime

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


async def main():
    # Ensure .env variables are loaded before reading config
    _load_env_file()

    cfg = load_config()

    # logging
    logging.basicConfig(level=getattr(logging, cfg.log_level, logging.INFO), format="%(asctime)s %(levelname)s %(message)s")
    logging.info(f"Starting with config: symbol={cfg.symbol}, interval={cfg.interval}")

    # tz
    tz = pytz.timezone(cfg.tz)

    # db
    db = DB(cfg.db_path)
    await db.init()

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

        # 检查是否有足够的K线数据（至少21根）才执行交易
        if len(ind.df) < cfg.window + 1:  # window=20, 所以需要至少21根
            logging.info(f"等待更多K线数据，当前: {len(ind.df)}/{cfg.window + 1}")
            return

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
        if up is not None and dn is not None:
            signal = decide(price, up, dn, state,
                            high_price=k.high, low_price=k.low,
                            is_closed=k.is_closed, only_on_close=cfg.only_on_close)
            if signal:
                await db.log_signal(int(time.time()*1000), signal, price)
                logging.info(f"Signal: {signal} @ {price} (UP={up:.2f}, DN={dn:.2f})")

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
                            logging.info(f"模拟平多开空: {qty:.3f} @ {price}")
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
            logging.debug(f"布林带指标未就绪，跳过策略决策 (UP={up}, DN={dn})")
            
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