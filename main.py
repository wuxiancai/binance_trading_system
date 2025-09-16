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
    logging.info(f"Starting with config: testnet={cfg.use_testnet}, symbol={cfg.symbol}, interval={cfg.interval}")

    # tz
    tz = pytz.timezone(cfg.tz)

    # db
    db = DB(cfg.db_path)
    await db.init()

    # trader
    trader = Trader(cfg.api_key, cfg.api_secret, cfg.rest_base, cfg.use_testnet,
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

    # ws
    ws = WSClient(cfg.ws_base, cfg.symbol, cfg.interval,
                  ping_interval=cfg.ws_ping_interval,
                  ping_timeout=cfg.ws_ping_timeout,
                  backoff_initial=cfg.ws_backoff_initial,
                  backoff_max=cfg.ws_backoff_max)

    state = StrategyState()

    async def on_kline(k: KlineEvent):
        # persist kline
        await db.insert_kline(k)
        ma, std, up, dn = ind.add_kline(k)
        if ma is None:
            return
        await db.upsert_indicator(k.open_time, ma, std, up, dn)

        # 仅在K线收盘处理策略（可配置）
        if cfg.only_on_close and not k.is_closed:
            return

        price = k.close

        # 从币安API获取实际仓位，确保交易决策基于真实仓位
        if cfg.api_key and cfg.api_secret:
            try:
                actual_position = trader.get_position_info(cfg.symbol)
                if actual_position is not None:
                    # 有仓位，更新本地状态
                    state.position = actual_position["position_side"]
                else:
                    # 无仓位
                    state.position = "flat"
            except Exception as e:
                logging.error(f"获取币安仓位失败，无法继续交易: {e}")
                # 强制要求API成功，不允许回退
                return

        signal = decide(price, up, dn, state)
        if signal:
            await db.log_signal(int(time.time()*1000), signal, price)
            logging.info(f"Signal: {signal} @ {price} (UP={up:.2f}, DN={dn:.2f})")

            if not (cfg.api_key and cfg.api_secret):
                return

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
                    qty = trader.calc_qty(cfg.symbol, price, cfg.max_position_pct)
                    if qty > 0:
                        close = trader.close_position(cfg.symbol, side="BUY", qty=qty)
                        await db.log_trade(int(time.time()*1000), "BUY_CLOSE", qty, price, str(close.get("orderId")), close.get("status"))
                        await db.update_trade_status_on_close("BUY_CLOSE")
                        open_ = trader.place_market(cfg.symbol, side="BUY", qty=qty)
                        await db.log_trade(int(time.time()*1000), "BUY_OPEN", qty, price, str(open_.get("orderId")), open_.get("status"))
                        # state已在strategy.py中更新
                        if cfg.stop_loss_enabled:
                            trader.place_stop_loss(cfg.symbol, position="long", entry_price=price, stop_loss_pct=cfg.stop_loss_pct)
                elif signal == "close_long_open_short":
                    # 平多仓+开空仓
                    qty = trader.calc_qty(cfg.symbol, price, cfg.max_position_pct)
                    if qty > 0:
                        close = trader.close_position(cfg.symbol, side="SELL", qty=qty)
                        await db.log_trade(int(time.time()*1000), "SELL_CLOSE", qty, price, str(close.get("orderId")), close.get("status"))
                        await db.update_trade_status_on_close("SELL_CLOSE")
                        open_ = trader.place_market(cfg.symbol, side="SELL", qty=qty)
                        await db.log_trade(int(time.time()*1000), "SELL_OPEN", qty, price, str(open_.get("orderId")), open_.get("status"))
                        # state已在strategy.py中更新
                        if cfg.stop_loss_enabled:
                            trader.place_stop_loss(cfg.symbol, position="short", entry_price=price, stop_loss_pct=cfg.stop_loss_pct)
                elif signal == "stop_loss_short":
                    # 空仓止损
                    qty = trader.calc_qty(cfg.symbol, price, cfg.max_position_pct)
                    if qty > 0:
                        order = trader.close_position(cfg.symbol, side="BUY", qty=qty)
                        await db.log_trade(int(time.time()*1000), "BUY_STOP_LOSS", qty, price, str(order.get("orderId")), order.get("status"))
                        await db.update_trade_status_on_close("BUY_STOP_LOSS")
                        # state已在strategy.py中更新为flat
                elif signal == "stop_loss_long":
                    # 多仓止损
                    qty = trader.calc_qty(cfg.symbol, price, cfg.max_position_pct)
                    if qty > 0:
                        order = trader.close_position(cfg.symbol, side="SELL", qty=qty)
                        await db.log_trade(int(time.time()*1000), "SELL_STOP_LOSS", qty, price, str(order.get("orderId")), order.get("status"))
                        await db.update_trade_status_on_close("SELL_STOP_LOSS")
                        # state已在strategy.py中更新为flat
            except Exception as e:
                logging.error(f"order failed: {e}")
                await db.log_error(int(time.time()*1000), "order", str(e))

    await ws.connect_and_listen(on_kline)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass