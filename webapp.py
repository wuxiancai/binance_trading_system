import threading
import subprocess
import sqlite3
import json
import urllib.request
import socket
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Optional, Dict, Any, List, Tuple

from flask import Flask, jsonify, Response, request
import statistics as stats
# New imports for WS realtime price
import asyncio
from ws_client import WSClient, KlineEvent


def _kill_port(port: int) -> None:
    """Kill process(es) listening on the given TCP port (best-effort)."""
    try:
        out = subprocess.check_output([
            "bash", "-lc", f"lsof -iTCP:{port} -sTCP:LISTEN -t || true"
        ], text=True)
        pids = [p.strip() for p in out.splitlines() if p.strip()]
        for pid in pids:
            try:
                subprocess.check_call(["bash", "-lc", f"kill -9 {pid} || true"])  # best-effort
            except subprocess.CalledProcessError:
                pass
    except Exception:
        # do not crash main app if lsof/kill not available
        pass


def _can_bind(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _recent_signals(db_path: str, limit: int = 20) -> List[Dict[str, Any]]:
    with _connect(db_path) as conn:
        cur = conn.execute(
            "SELECT ts, signal, price FROM signals ORDER BY ts DESC LIMIT ?", (limit,)
        )
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["ts_local"] = _fmt_ts(r["ts"])
        return rows





def _recent_trades(db_path: str, limit: int = 50) -> List[Dict[str, Any]]:
    with _connect(db_path) as conn:
        cur = conn.execute(
            "SELECT ts, side, qty, price, order_id, status FROM trades ORDER BY ts DESC LIMIT ?",
            (limit,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        
        # 为每笔交易添加时间格式化、操作类型和方向
        for r in rows:
            r["ts_local"] = _fmt_ts(r["ts"])
            r["pnl"] = None  # 默认无盈亏
            
            # 根据side字段确定操作类型和方向
            side = r["side"]
            if side in ["BUY", "BUY_OPEN"]:
                r["action_type"] = "买"  # 开仓多头
                r["direction"] = "LONG"
            elif side in ["SELL", "SELL_OPEN"]:
                r["action_type"] = "买"  # 开仓空头
                r["direction"] = "SHORT"
            elif side == "BUY_CLOSE":
                r["action_type"] = "平"  # 平仓
                r["direction"] = "SHORT"  # 平的是空仓
            elif side == "BUY_STOP_LOSS":
                r["action_type"] = "平"  # 止损平仓
                r["direction"] = "SHORT"  # 平的是空仓
            elif side == "SELL_CLOSE":
                r["action_type"] = "平"  # 平仓
                r["direction"] = "LONG"   # 平的是多仓
            elif side == "SELL_STOP_LOSS":
                r["action_type"] = "平"  # 止损平仓
                r["direction"] = "LONG"   # 平的是多仓
            else:
                r["action_type"] = "未知"
                r["direction"] = "未知"
        
        # 获取所有交易记录用于配对计算盈亏
        cur_all = conn.execute(
            "SELECT ts, side, qty, price FROM trades WHERE side IN ('BUY','SELL','BUY_CLOSE','SELL_CLOSE','BUY_OPEN','SELL_OPEN') ORDER BY ts ASC"
        )
        all_trades = cur_all.fetchall()
        
        # 创建交易配对的盈亏映射
        pnl_map = {}  # {timestamp: pnl}
        
        # 配对交易计算盈亏
        i = 0
        while i < len(all_trades) - 1:
            trade1 = all_trades[i]
            trade2 = all_trades[i + 1]
            
            side1 = trade1["side"]
            side2 = trade2["side"]
            price1 = float(trade1["price"]) if trade1["price"] is not None else None
            price2 = float(trade2["price"]) if trade2["price"] is not None else None
            qty1 = float(trade1["qty"]) if trade1["qty"] is not None else 0.0
            qty2 = float(trade2["qty"]) if trade2["qty"] is not None else 0.0
            
            if price1 is None or price2 is None:
                i += 1
                continue
            
            # 检查是否为有效的交易对
            pnl = 0.0
            
            # BUY -> SELL (多仓盈亏)
            if side1 in ("BUY", "BUY_OPEN") and side2 in ("SELL", "SELL_CLOSE"):
                pnl = (price2 - price1) * min(qty1, qty2)  # 平仓金额 - 开仓金额
                pnl_map[trade1["ts"]] = -pnl  # 开仓交易显示负值（投入）
                pnl_map[trade2["ts"]] = pnl   # 平仓交易显示盈亏
                i += 2
            # SELL -> BUY (空仓盈亏)  
            elif side1 in ("SELL", "SELL_OPEN") and side2 in ("BUY", "BUY_CLOSE"):
                pnl = (price1 - price2) * min(qty1, qty2)  # 平仓金额 - 开仓金额
                pnl_map[trade1["ts"]] = -pnl  # 开仓交易显示负值（投入）
                pnl_map[trade2["ts"]] = pnl   # 平仓交易显示盈亏
                i += 2
            else:
                i += 1
        
        # 将盈亏信息添加到交易记录中
        for r in rows:
            if r["ts"] in pnl_map:
                r["pnl"] = pnl_map[r["ts"]]
        
        return rows


def _get_latest_open_time(db_path: str) -> Optional[int]:
    """获取最近的开仓时间"""
    with _connect(db_path) as conn:
        # 查找最近的开仓交易（状态为NEW的开仓交易）
        cur = conn.execute(
            "SELECT ts FROM trades WHERE side IN ('BUY_OPEN', 'SELL_OPEN', 'BUY', 'SELL') AND status = 'NEW' ORDER BY ts DESC LIMIT 1"
        )
        row = cur.fetchone()
        if row:
            return row["ts"]
        
        # 如果没有找到NEW状态的开仓交易，查找最近的开仓交易
        cur = conn.execute(
            "SELECT ts FROM trades WHERE side IN ('BUY_OPEN', 'SELL_OPEN', 'BUY', 'SELL') ORDER BY ts DESC LIMIT 1"
        )
        row = cur.fetchone()
        if row:
            return row["ts"]
        
        return None


def _compute_current_position(db_path: str, trader: Optional[Any] = None, symbol: str = "BTCUSDT") -> Dict[str, Any]:
    """获取当前仓位信息，强制使用币安API实际数据，确保所有交易决策基于真实仓位"""
    
    # 当没有传入 trader 实例时，前端展示降级为“空仓”，避免接口 500（用于本地预览/无交易环境）
    if trader is None:
        ts_now = int(time.time() * 1000)
        return {
            "position": "flat",
            "ts": ts_now,
            "ts_local": _fmt_ts(ts_now),
            "source": "no_trader"
        }
    
    try:
        position_info = trader.get_position_info(symbol)
        if position_info is not None:
            # 有实际仓位，获取实际的开仓时间
            open_time = _get_latest_open_time(db_path)
            if open_time is None:
                # 如果没有找到开仓时间，使用当前时间
                open_time = int(time.time() * 1000)
            
            return {
                "position": position_info["position_side"],
                "contract": position_info["contract"],  # 合约名称
                "quantity": position_info["quantity"],  # 数量
                "entry_price": position_info["entry_price"],
                "margin_balance": position_info["margin_balance"],  # 保证金余额
                "position_initial_margin": position_info["position_initial_margin"],  # 开仓金额
                "pnl": position_info["pnl"],  # 盈亏
                "pnl_percentage": position_info["pnl_percentage"],  # 盈亏回报率
                "mark_price": position_info["mark_price"],
                "leverage": position_info["leverage"],
                "margin_ratio": position_info["margin_ratio"],  # 保证金比例
                "liquidation_price": position_info["liquidation_price"],  # 强平价格
                "ts": open_time,  # 使用实际的开仓时间
                "ts_local": _fmt_ts(open_time),  # 使用实际的开仓时间
                "source": "binance_api"
            }
        else:
            # API显示无仓位
            return {
                "position": "flat",
                "ts": int(time.time() * 1000),
                "ts_local": _fmt_ts(int(time.time() * 1000)),
                "source": "binance_api"
            }
    except Exception as e:
        # API调用失败，抛出异常而不是回退
        raise RuntimeError(f"获取币安仓位信息失败，无法继续交易: {e}") from e


def _compute_last_closed_pnl(db_path: str) -> Optional[Dict[str, Any]]:
    """Find the latest completed trade pair to compute realized PnL."""
    with _connect(db_path) as conn:
        # 获取所有交易记录，按时间排序
        cur = conn.execute(
            "SELECT ts, side, qty, price FROM trades WHERE side IN ('BUY','SELL','BUY_CLOSE','SELL_CLOSE','BUY_OPEN','SELL_OPEN') ORDER BY ts ASC"
        )
        all_trades = cur.fetchall()
        
        # 找到最后一个完成的交易对
        last_completed = None
        i = 0
        while i < len(all_trades) - 1:
            trade1 = all_trades[i]
            trade2 = all_trades[i + 1]
            
            side1 = trade1["side"]
            side2 = trade2["side"]
            price1 = float(trade1["price"]) if trade1["price"] is not None else None
            price2 = float(trade2["price"]) if trade2["price"] is not None else None
            qty1 = float(trade1["qty"]) if trade1["qty"] is not None else 0.0
            qty2 = float(trade2["qty"]) if trade2["qty"] is not None else 0.0
            
            if price1 is None or price2 is None:
                i += 1
                continue
            
            # 检查是否为有效的交易对
            # BUY -> SELL (多仓盈亏)
            if side1 in ("BUY", "BUY_OPEN") and side2 in ("SELL", "SELL_CLOSE"):
                pnl = (price2 - price1) * min(qty1, qty2)
                last_completed = {
                    "side": "long",
                    "entry_price": price1,
                    "exit_price": price2,
                    "qty": min(qty1, qty2),
                    "pnl": pnl,
                    "open_time": trade1["ts"],
                    "open_time_local": _fmt_ts(trade1["ts"]),
                    "close_time": trade2["ts"],
                    "close_time_local": _fmt_ts(trade2["ts"]),
                }
                i += 2
            # SELL -> BUY (空仓盈亏)  
            elif side1 in ("SELL", "SELL_OPEN") and side2 in ("BUY", "BUY_CLOSE"):
                pnl = (price1 - price2) * min(qty1, qty2)
                last_completed = {
                    "side": "short",
                    "entry_price": price1,
                    "exit_price": price2,
                    "qty": min(qty1, qty2),
                    "pnl": pnl,
                    "open_time": trade1["ts"],
                    "open_time_local": _fmt_ts(trade1["ts"]),
                    "close_time": trade2["ts"],
                    "close_time_local": _fmt_ts(trade2["ts"]),
                }
                i += 2
            else:
                i += 1
        
        return last_completed


def _latest_price(db_path: str) -> Optional[float]:
    """获取最新价格（从最新的K线数据）"""
    try:
        with _connect(db_path) as conn:
            cur = conn.execute("SELECT close FROM klines ORDER BY open_time DESC LIMIT 1")
            row = cur.fetchone()
            if row:
                return float(row["close"])
    except Exception:
        pass
    return None


def _get_error_logs(db_path: str, limit: int = 50) -> List[Dict[str, Any]]:
    """获取错误日志记录"""
    with _connect(db_path) as conn:
        cur = conn.execute(
            "SELECT ts, where_, error FROM errors ORDER BY ts DESC LIMIT ?", (limit,)
        )
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["ts_local"] = _fmt_ts(r["ts"])
        return rows


def _get_pnl_records(db_path: str, limit: int = 20) -> List[Dict[str, Any]]:
    """获取所有交易的盈亏记录"""
    records = []
    with _connect(db_path) as conn:
        # 获取所有交易记录，按时间排序
        cur = conn.execute(
            "SELECT ts, side, qty, price FROM trades WHERE side IN ('BUY','SELL','BUY_CLOSE','SELL_CLOSE','BUY_OPEN','SELL_OPEN') ORDER BY ts ASC"
        )
        all_trades = cur.fetchall()
        
        # 配对交易计算盈亏
        i = 0
        while i < len(all_trades) - 1:
            trade1 = all_trades[i]
            trade2 = all_trades[i + 1]
            
            side1 = trade1["side"]
            side2 = trade2["side"]
            price1 = float(trade1["price"]) if trade1["price"] is not None else None
            price2 = float(trade2["price"]) if trade2["price"] is not None else None
            qty1 = float(trade1["qty"]) if trade1["qty"] is not None else 0.0
            qty2 = float(trade2["qty"]) if trade2["qty"] is not None else 0.0
            
            if price1 is None or price2 is None:
                i += 1
                continue
            
            # 检查是否为有效的交易对
            pnl = 0.0
            
            # BUY -> SELL (多仓盈亏)
            if side1 in ("BUY", "BUY_OPEN") and side2 in ("SELL", "SELL_CLOSE"):
                pnl = (price2 - price1) * min(qty1, qty2)
                records.append({
                    "ts": trade2["ts"],
                    "ts_local": _fmt_ts(trade2["ts"]),
                    "side": "long",
                    "entry_price": price1,
                    "exit_price": price2,
                    "qty": min(qty1, qty2),
                    "pnl": pnl
                })
                # 跳过已配对的交易
                i += 2
            # SELL -> BUY (空仓盈亏)  
            elif side1 in ("SELL", "SELL_OPEN") and side2 in ("BUY", "BUY_CLOSE"):
                pnl = (price1 - price2) * min(qty1, qty2)
                records.append({
                    "ts": trade2["ts"],
                    "ts_local": _fmt_ts(trade2["ts"]),
                    "side": "short",
                    "entry_price": price1,
                    "exit_price": price2,
                    "qty": min(qty1, qty2),
                    "pnl": pnl
                })
                # 跳过已配对的交易
                i += 2
            else:
                i += 1
        
        # 按时间倒序排列，限制数量
        records.sort(key=lambda x: x["ts"], reverse=True)
        return records[:limit]


def _get_daily_stats(db_path: str, days: int = 7, trader: Optional[Any] = None) -> List[Dict[str, Any]]:
    """获取每日交易统计"""
    stats = []
    
    # 获取保证金余额用于计算利润率
    margin_balance = 1000.0  # 默认值
    if trader:
        try:
            position_info = trader.get_position_info()
            margin_balance = position_info.get("margin_balance", 1000.0)
        except:
            margin_balance = 1000.0
    
    with _connect(db_path) as conn:
        # 获取所有交易记录，按时间排序
        cur = conn.execute(
            "SELECT ts, side, qty, price FROM trades WHERE side IN ('BUY','SELL','BUY_CLOSE','SELL_CLOSE','BUY_OPEN','SELL_OPEN') ORDER BY ts ASC"
        )
        all_trades = cur.fetchall()
        
        # 按日期分组统计
        daily_data = {}
        
        # 配对交易计算盈亏
        i = 0
        while i < len(all_trades) - 1:
            trade1 = all_trades[i]
            trade2 = all_trades[i + 1]
            
            side1 = trade1["side"]
            side2 = trade2["side"]
            price1 = float(trade1["price"]) if trade1["price"] is not None else None
            price2 = float(trade2["price"]) if trade2["price"] is not None else None
            qty1 = float(trade1["qty"]) if trade1["qty"] is not None else 0.0
            qty2 = float(trade2["qty"]) if trade2["qty"] is not None else 0.0
            
            if price1 is None or price2 is None:
                i += 1
                continue
            
            # 检查是否为有效的交易对
            pnl = 0.0
            trade_date = None
            
            # BUY -> SELL (多仓盈亏)
            if side1 in ("BUY", "BUY_OPEN") and side2 in ("SELL", "SELL_CLOSE"):
                pnl = (price2 - price1) * min(qty1, qty2)
                trade_date = _fmt_ts(trade2["ts"]).split(' ')[0]
            # SELL -> BUY (空仓盈亏)  
            elif side1 in ("SELL", "SELL_OPEN") and side2 in ("BUY", "BUY_CLOSE"):
                pnl = (price1 - price2) * min(qty1, qty2)
                trade_date = _fmt_ts(trade2["ts"]).split(' ')[0]
            
            if trade_date:
                if trade_date not in daily_data:
                    daily_data[trade_date] = {'trades': 0, 'total_pnl': 0.0}
                
                daily_data[trade_date]['trades'] += 1
                daily_data[trade_date]['total_pnl'] += pnl
                
                # 跳过已配对的交易
                i += 2
            else:
                i += 1
        
        # 转换为列表并计算利润率
        for date_str, data in sorted(daily_data.items(), reverse=True)[:days]:
            # 利润率 = 利润总和 / 保证金余额 * 100
            profit_rate = (data['total_pnl'] / margin_balance) * 100 if margin_balance > 0 else 0.0
            
            stats.append({
                'date': date_str,
                'trades_count': data['trades'],
                'total_pnl': data['total_pnl'],
                'profit_rate': profit_rate
            })
    
    return stats


def _log_trade_sync(db_path: str, ts: int, side: str, qty: float, price: float | None, order_id: str | None, status: str | None) -> None:
    try:
        with _connect(db_path) as conn:
            conn.execute(
                "INSERT INTO trades(ts, side, qty, price, order_id, status) VALUES (?,?,?,?,?,?)",
                (ts, side, qty, price, order_id, status),
            )
            conn.commit()
    except Exception:
        pass


def create_app(cfg: Any, trader: Optional[Any] = None) -> Flask:
    app = Flask(__name__)
    # expose trader instance to routes for test order
    app.config["TRADER"] = trader
    # set timezone for UI formatting
    try:
        _set_tz(getattr(cfg, "tz", "Asia/Shanghai"))
    except Exception:
        pass

    # Cache minimal config for UI
    app.config["SUMMARY_CFG"] = {
        "symbol": getattr(cfg, "symbol", None),
        "interval": getattr(cfg, "interval", None),
        "leverage": getattr(cfg, "leverage", None),
        "max_position_pct": getattr(cfg, "max_position_pct", None),
        "window": getattr(cfg, "window", None),
        "only_on_close": getattr(cfg, "only_on_close", None),
        "stop_loss_enabled": getattr(cfg, "stop_loss_enabled", None),
        "stop_loss_pct": getattr(cfg, "stop_loss_pct", None),
        "tz": getattr(cfg, "tz", None),
        "log_level": getattr(cfg, "log_level", None),
        "db_path": getattr(cfg, "db_path", "trader.db"),
        # New: expose ws base for WS price feed
        "ws_base": getattr(cfg, "ws_base", "wss://fstream.binance.com"),
        # Optional: expose compute params
        "boll_multiplier": getattr(cfg, "boll_multiplier", 2.0),
        "boll_ddof": getattr(cfg, "boll_ddof", 0),
    }

    # New: ensure WS price feed background thread started
    try:
        _ensure_ws_price_feed(app)
    except Exception:
        pass

    @app.get("/api/summary")
    def api_summary() -> Response:
        c = app.config["SUMMARY_CFG"]
        db_path = c["db_path"]
        trader_obj = app.config.get("TRADER")
        symbol = c.get("symbol", "BTCUSDT")
        position = _compute_current_position(db_path, trader_obj, symbol)
        last_closed = _compute_last_closed_pnl(db_path)
        signals = _recent_signals(db_path, limit=20)
        trades = _recent_trades(db_path, limit=20)
        pnl_records = _get_pnl_records(db_path, limit=20)
        daily_stats = _get_daily_stats(db_path, days=7, trader=trader_obj)
        error_logs = _get_error_logs(db_path, limit=30)
        # New: realtime boll
        rt_boll = _get_realtime_boll(db_path, c.get("window", 20), c.get("boll_multiplier", 2.0), c.get("boll_ddof", 0), symbol)
        # New: strategy status
        strategy_status = _get_strategy_status(db_path)
        # enrich position with leverage (only if not already set by API)
        if position.get("position") in ("long", "short") and "leverage" not in position:
            position["leverage"] = c["leverage"]
        return jsonify({
            "config": {**c, "web_port": app.config.get("WEB_PORT", 5000)},
            "position": position,
            "realtime_boll": rt_boll,
            "strategy_status": strategy_status,
            "last_closed": last_closed,
            "signals": signals,
            "trades": trades,
            "pnl_records": pnl_records,
            "daily_stats": daily_stats,
            "error_logs": error_logs,
        })

    @app.post("/api/test_order")
    def api_test_order() -> Response:
        # 已禁用测试下单接口
        return jsonify({"ok": False, "error": "test order API disabled"}), 404
        c = app.config["SUMMARY_CFG"]
        trader_obj = app.config.get("TRADER")
        if trader_obj is None:
            return jsonify({"ok": False, "error": "trader not ready"}), 503
        data = request.get_json(silent=True) or {}
        side = str(data.get("side", "BUY")).upper()
        if side not in ("BUY", "SELL"):
            side = "BUY"
        try:
            max_pct = float(c.get("max_position_pct") or 0.1)
        except Exception:
            max_pct = 0.1
        default_pct = min(max_pct, 0.01)
        try:
            pct = float(data.get("percent", default_pct))
        except Exception:
            pct = default_pct
        pct = max(0.001, min(max_pct, pct))

        price = _latest_price(c["db_path"]) or None
        if price is None:
            try:
                t = trader_obj.client.futures_symbol_ticker(symbol=c["symbol"])  # type: ignore[attr-defined]
                price = float(t.get("price"))
            except Exception:
                price = None
        if price is None:
            return jsonify({"ok": False, "error": "cannot determine price"}), 400

        try:
            qty = trader_obj.calc_qty(c["symbol"], price, pct)
            if qty <= 0:
                return jsonify({"ok": False, "error": "calculated qty <= 0"}), 400
            order = trader_obj.place_market(c["symbol"], side=side, qty=qty)
            order_id = str(order.get("orderId"))
            status = order.get("status")
            ts = int(time.time() * 1000)
            _log_trade_sync(c["db_path"], ts, side, qty, price, order_id, status)
            return jsonify({"ok": True, "side": side, "qty": qty, "price": price, "order_id": order_id, "status": status})
        except Exception as e:
            # best-effort error log
            try:
                with _connect(c["db_path"]) as conn:
                    conn.execute("INSERT INTO errors(ts, where_, error) VALUES (?,?,?)", (int(time.time()*1000), "api_test_order", str(e)))
                    conn.commit()
            except Exception:
                pass
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.get("/")
    def index() -> Response:
        # Simple HTML with auto-refreshing summary
        html = """
        <!doctype html>
        <html>
        <head>
            <meta charset="utf-8" />
            <title>Binance Trader Dashboard</title>
            <style>
                 :root {
                   --bg: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                   --bg-solid: #f8fafc;
                   --fg:#1e293b; --muted:#64748b; --card:#ffffff; --border:#e2e8f0; --accent:#3b82f6; --thead:#f8fafc;
                   --success: #10b981; --danger: #ef4444; --warning: #f59e0b;
                   --shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
                   --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
                 }
                 html,body{ height:100%; margin:0; }
                 body { 
                   font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; 
                   background: var(--bg); 
                   color: var(--fg); 
                   line-height: 1.6;
                 }
                 .container{ max-width: 1600px; margin: 0 auto; padding: 8px 8px; }
                 .header{ 
                   display:flex; align-items:center; justify-content:center; 
                   margin-bottom: 12px; padding: 8px 16px; background: rgba(255,255,255,0.95); 
                   border-radius: 8px; box-shadow: var(--shadow);
                 }
                 .btn{ 
                   appearance:none; border:2px solid var(--accent); background:var(--accent); color:white; 
                   padding:8px 16px; border-radius:8px; cursor:pointer; font-size:13px; font-weight:600;
                   transition: all 0.2s ease; text-transform: uppercase; letter-spacing: 0.3px;
                 }
                 .btn:hover{ transform: translateY(-1px); box-shadow: var(--shadow-lg); }
                 .btn.warn{ border-color:var(--danger); background:var(--danger); }
                 .btn.warn:hover{ background:#dc2626; }
                 h1 { margin: 0; font-size: 20px; font-weight: 700; color: var(--fg); letter-spacing: -0.3px; text-align:center; width: 100%; }
                 small { color: var(--muted); }
                 .grid { display: grid; grid-template-columns: repeat(2, minmax(420px, 1fr)); gap: 10px; align-items:start; max-width: 1600px; margin-left: auto; margin-right: auto; }
                 .card { 
                   background:var(--card); border: 1px solid var(--border); border-radius: 8px; 
                   padding: 12px; box-shadow: var(--shadow); transition: all 0.2s ease;
                 }
                 .card:hover { transform: translateY(-2px); box-shadow: var(--shadow-lg); }
                 .card h3{ margin: 0 0 8px; font-size: 15px; font-weight: 600; color: var(--fg); }
                 .table-wrap{ max-height: 350px; overflow:auto; border-radius: 6px; }
                 table { width: 100%; border-collapse: collapse; table-layout: fixed; }
                 th, td { 
                   border-bottom: 1px solid var(--border); padding: 6px 4px; text-align: left; 
                   white-space: nowrap; overflow:hidden; text-overflow: ellipsis; font-size: 13px; 
                   line-height: 1.3;
                 }
                 th { 
                   position: sticky; top: 0; background: var(--thead); z-index: 1; 
                   font-weight: 600; color: var(--fg); text-transform: uppercase; 
                   font-size: 11px; letter-spacing: 0.3px; padding: 4px;
                 }
                 .ok { color: var(--success); font-weight: 600; }
                 .warn { color: var(--warning); font-weight: 600; }
                 .err { color: var(--danger); font-weight: 600; }
                 .dir-long { color: var(--success); font-weight: 600; font-size: 12px; }
                 .dir-short { color: var(--danger); font-weight: 600; font-size: 12px; }
                 .dir-buy { color: var(--success); font-weight: 600; font-size: 12px; }
                 .dir-sell { color: var(--danger); font-weight: 600; font-size: 12px; }
                 .bool-true { color: var(--danger); font-weight: 500; background: rgba(239, 68, 68, 0.1); padding: 1px 4px; border-radius: 3px; font-size: 11px; }
                 .pnl-profit { color: var(--success); font-weight: 600; }
                 .pnl-loss { color: var(--danger); font-weight: 600; }
                 .status-new { color: var(--warning); font-weight: 500; font-size: 11px; }
                 .status-over { color: var(--muted); font-weight: 500; font-size: 11px; }
              </style>
        </head>
        <body>
            <div class="container">
              <div class="header">
                <h1>Binance Trader Dashboard</h1>
              </div>
              <div class="grid" id="cards"></div>
            </div>
            <script>
                 const boolCell = (v) => `<span class="${v ? 'bool-true' : ''}">${v}</span>`;
                 const dirClass = (s) => {
                   if (!s) return '';
                   const u = String(s).toUpperCase();
                   if (u.includes('BUY')) return 'dir-long';
                   if (u.includes('SELL')) return 'dir-short';
                   if (u === 'LONG') return 'dir-long';
                   if (u === 'SHORT') return 'dir-short';
                   return '';
                 };
                 // 已移除 testOrder 函数与相关按钮

                 async function load() {
                     const res = await fetch('/api/summary');
                     const data = await res.json();
                     const cfg = data.config;
                     const cards = [];
                    const dash = '--';
                    const fmt = (v, digits=2) => (v==null || v==="" ? dash : (typeof v === 'number' ? v.toFixed(digits) : v));
 
                     // Config
                     cards.push(`
                     <div class="card">
                         <h3>当前配置</h3>
                         <table>
                           <tr><th>合约币对</th><td>${cfg.symbol}</td></tr>
                           <tr><th>K线时间窗口</th><td>${cfg.interval}</td></tr>
                           
                           <tr><th>杠杆</th><td>${cfg.leverage}</td></tr>
                           <tr><th>最大仓位 %</th><td>${cfg.max_position_pct}</td></tr>
                           <tr><th>WINDOW</th><td>${cfg.window}</td></tr>
                           <tr><th>K 线是否仅在收盘时执行</th><td>${boolCell(cfg.only_on_close)}</td></tr>
                           <tr><th>止损</th><td>${boolCell(cfg.stop_loss_enabled)} (pct=${cfg.stop_loss_pct})</td></tr>
                           <tr><th>时区</th><td>${cfg.tz}</td></tr>
                           <tr><th>日志级别</th><td>${cfg.log_level}</td></tr>
                           <tr><th>Web Port</th><td>${cfg.web_port}</td></tr>
                         </table>
                     </div>`);
 
                     // Position (render before trades)
                     const p = data.position || {};
                     if (p.position === 'long' || p.position === 'short') {
                      cards.push(`
                        <div class="card">
                          <h3>当前仓位</h3>
                          <table>
                            <tr><th>合约</th><td>${p.contract || dash}</td></tr>
                            <tr><th>数量</th><td>${fmt(p.quantity, 6)} BTC</td></tr>
                            <tr><th>方向</th><td><span class="${dirClass(p.position)}">${fmt(p.position, 0)}</span></td></tr>
                            <tr><th>入场价格</th><td>${fmt(p.entry_price)}</td></tr>
                            <tr><th>标记价格</th><td>${fmt(p.mark_price)}</td></tr>
                            <tr><th>保证金余额</th><td>${fmt(p.margin_balance, 2)} USDT</td></tr>
                            <tr><th>开仓金额</th><td>${fmt(p.position_initial_margin, 2)} USDT</td></tr>
                            <tr><th>盈亏(回报率)</th><td><span class="${p.pnl >= 0 ? 'pnl-profit' : 'pnl-loss'}">${fmt(p.pnl, 2)} USDT (${fmt(p.pnl_percentage, 2)}%)</span></td></tr>
                            <tr><th>杠杆</th><td>${fmt(p.leverage, 0)}x</td></tr>
                            <tr><th>保证金比例</th><td>${fmt(p.margin_ratio, 2)}%</td></tr>
                            <tr><th>强平价格</th><td>${fmt(p.liquidation_price, 2)}</td></tr>
                            <tr><th>建仓时间</th><td>${p.ts_local ?? dash}</td></tr>
                          </table>
                        </div>`);
                     } else {
                      cards.push(`
                        <div class="card">
                          <h3>当前仓位</h3>
                          <table>
                            <tr><th>合约</th><td>${dash}</td></tr>
                            <tr><th>数量</th><td>${dash}</td></tr>
                            <tr><th>方向</th><td>${dash}</td></tr>
                            <tr><th>入场价格</th><td>${dash}</td></tr>
                            <tr><th>标记价格</th><td>${dash}</td></tr>
                            <tr><th>保证金余额</th><td>${dash}</td></tr>
                            <tr><th>开仓金额</th><td>${dash}</td></tr>
                            <tr><th>盈亏</th><td>${dash}</td></tr>
                            <tr><th>杠杆</th><td>${dash}</td></tr>
                            <tr><th>保证金比例</th><td>${dash}</td></tr>
                            <tr><th>强平价格</th><td>${dash}</td></tr>
                            <tr><th>建仓时间</th><td>${dash}</td></tr>
                          </table>
                        </div>`);
                     }

                     // PnL function for trades table
                     const pnlClass = (pnl) => {
                       if (pnl == null) return '';
                       return Number(pnl) >= 0 ? 'pnl-profit' : 'pnl-loss';
                     };

                     // BOLL UP DN (REALTIME) - moved to first position
                     const rt = data.realtime_boll || {};
                     const rtUp = rt.up ? fmt(rt.up) : '--';
                     const rtDn = rt.dn ? fmt(rt.dn) : '--';
                     const rtMa = rt.ma ? fmt(rt.ma) : '--';
                     const rtPrice = (rt.price != null) ? Number(rt.price).toFixed(2) : '--';
                     const rtSrc = rt.source ? String(rt.source) : '';
                     const _pad2 = (n) => String(n).padStart(2, '0');
                     const _now = new Date();
                     const _nowStr = `${_pad2(_now.getMonth()+1)}-${_pad2(_now.getDate())} ${_pad2(_now.getHours())}:${_pad2(_now.getMinutes())}:${_pad2(_now.getSeconds())}`;
                     
                     // Strategy status
                     const strategy = data.strategy_status || {};
                     const breakoutUp = strategy.breakout_up ? 'YES' : 'NO';
                     const breakoutDn = strategy.breakout_dn ? 'YES' : 'NO';
                     const status = strategy.status || 'NONE';
                     const breakoutUpColor = strategy.breakout_up ? '#ff6b6b' : '#64748b';
                     const breakoutDnColor = strategy.breakout_dn ? '#45b7d1' : '#64748b';
                     const statusColor = status === 'waiting_for_long' ? '#4ecdc4' : status === 'waiting_for_short' ? '#ff6b6b' : '#64748b';
                     
                     cards.push(`
                       <div class="card">
                         <h3>BOLL UP DN (REALTIME)</h3>
                        <div class="table-wrap">
                          <table>
                            <tr><th style=\"width:20%\">指标</th><th style=\"width:25%\">价格</th><th style=\"width:25%\">更新时间</th><th style=\"width:30%\">策略状态</th></tr>
                            <tr><td>最新价</td><td style=\"font-weight: bold;\">${rtPrice}</td><td id=\"rt-boll-time\" rowspan=\"4\" style=\"vertical-align: middle; font-size: 12px;\">${_nowStr}${rtSrc ? ` <small style=\"color:#64748b\">(${rtSrc})</small>` : ''}</td><td style=\"font-size: 11px;\">突破UP: <span style=\"color: ${breakoutUpColor}; font-weight: bold;\">${breakoutUp}</span></td></tr>
                            <tr><td>BOLL UP</td><td style=\"color: #ff6b6b; font-weight: bold;\">${rtUp}</td><td style=\"font-size: 11px;\">跌破DN: <span style=\"color: ${breakoutDnColor}; font-weight: bold;\">${breakoutDn}</span></td></tr>
                            <tr><td>BOLL MA</td><td style=\"color: #4ecdc4; font-weight: bold;\">${rtMa}</td><td style=\"font-size: 11px;\">状态: <span style=\"color: ${statusColor}; font-weight: bold;\">${status}</span></td></tr>
                            <tr><td>BOLL DN</td><td style=\"color: #45b7d1; font-weight: bold;\">${rtDn}</td><td></td></tr>
                          </table>
                        </div>
                       </div>`);

                     // Daily Stats (moved to second position)
                     const statsRows = (data.daily_stats || []).map(s => `<tr><td>${s.date}</td><td>${s.trades_count}</td><td><span class="${pnlClass(s.total_pnl)}">${fmt(s.total_pnl)}</span></td><td><span class="${pnlClass(s.profit_rate)}">${fmt(s.profit_rate)}%</span></td></tr>`).join('');
                     cards.push(`
                       <div class="card">
                         <h3>每日交易统计</h3>
                        <div class="table-wrap">
                          <table>
                            <tr><th style="width:28%">日期</th><th style="width:20%">次数</th><th style="width:26%">利润总和</th><th style="width:26%">利润率</th></tr>
                            ${statsRows}
                          </table>
                        </div>
                       </div>`);

                     // Error Logs (new card after daily stats)
                     const logRows = (data.error_logs || []).map(log => {
                       const errorText = log.error || '';
                       const isError = errorText.toLowerCase().includes('error') || errorText.toLowerCase().includes('failed') || errorText.toLowerCase().includes('exception');
                       const errorClass = isError ? 'err' : '';
                       return `<tr><td>${log.ts_local}</td><td>${log.where_ || ''}</td><td><span class="${errorClass}">${errorText}</span></td></tr>`;
                     }).join('');
                     cards.push(`
                       <div class="card">
                         <h3>日志</h3>
                        <div class="table-wrap">
                          <table>
                            <tr><th style="width:20%">时间</th><th style="width:25%">位置</th><th style="width:55%">错误信息</th></tr>
                            ${logRows}
                          </table>
                        </div>
                       </div>`);
 
                     // Recent trades
                    const statusClass = (status) => {
                      if (!status) return '';
                      const s = String(status).toUpperCase();
                      if (s === 'NEW') return 'status-new';
                      if (s === 'OVER') return 'status-over';
                      return '';
                    };
                    
                    // 交易记录，显示时间、买/平、方向、数量、价格
                    const tdRows = (data.trades || []).map(t => `<tr><td>${t.ts_local}</td><td><span class="${t.action_type === '买' ? 'dir-buy' : 'dir-sell'}">${t.action_type}</span></td><td><span class="${dirClass(t.direction)}">${t.direction}</span></td><td>${t.qty}</td><td>${t.price ?? ''}</td></tr>`).join('');
                     cards.push(`
                       <div class="card">
                         <h3>最近交易</h3>
                        <div class="table-wrap">
                          <table>
                            <tr><th style="width:20%">时间</th><th style="width:15%">买/平</th><th style="width:15%">方向</th><th style="width:25%">数量</th><th style="width:25%">价格</th></tr>
                            ${tdRows}
                          </table>
                        </div>
                       </div>`);

                     // Last closed PnL
                     const lc = data.last_closed;
                     if (lc) {
                       cards.push(`
                         <div class="card">
                           <h3>最近一次平仓</h3>
                           <table>
                             <tr><th>方向</th><td><span class="${dirClass(lc.side)}">${lc.side}</span></td></tr>
                             <tr><th>开仓价</th><td>${lc.entry_price}</td></tr>
                             <tr><th>平仓价</th><td>${lc.exit_price}</td></tr>
                             <tr><th>数量</th><td>${lc.qty}</td></tr>
                             <tr><th>已实现收益</th><td>${lc.pnl}</td></tr>
                             <tr><th>开仓时间</th><td>${lc.open_time_local}</td></tr>
                             <tr><th>平仓时间</th><td>${lc.close_time_local}</td></tr>
                           </table>
                         </div>`);
                     }
 
 

 

 
                     document.getElementById('cards').innerHTML = cards.join('');
                 }
                 load();
                 setInterval(load, 3000);
                 if (!window._rtClockInterval) {
                   window._rtClockInterval = setInterval(() => {
                     const el = document.getElementById('rt-boll-time');
                     if (el) {
                       const d = new Date();
                       const p2 = (n) => String(n).padStart(2, '0');
                       el.textContent = `${p2(d.getMonth()+1)}-${p2(d.getDate())} ${p2(d.getHours())}:${p2(d.getMinutes())}:${p2(d.getSeconds())}`;
                     }
                   }, 1000);
                 }
            </script>
        </body>
        </html>
        """
        return Response(html, mimetype="text/html")

    @app.get("/api/health")
    def api_health() -> Response:
        return jsonify({"status": "ok"})

    return app


_def_server_thread: Optional[threading.Thread] = None


def start_web_server(cfg: Any, trader: Optional[Any] = None) -> int:
    global _def_server_thread
    # 严格固定 5000 端口：尝试多次释放并绑定
    port = 5000
    for _ in range(3):
        if _can_bind(port):
            break
        _kill_port(port)
    app = create_app(cfg, trader)
    app.config["WEB_PORT"] = port

    def run():
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)

    t = threading.Thread(target=run, name="WebServer", daemon=True)
    t.start()
    _def_server_thread = t
    return port


_TZ_NAME: str = "Asia/Shanghai"
_TZ = ZoneInfo(_TZ_NAME)


def _set_tz(name: str) -> None:
    global _TZ_NAME, _TZ
    try:
        _TZ = ZoneInfo(name)
        _TZ_NAME = name
    except Exception:
        _TZ = ZoneInfo("Asia/Shanghai")
        _TZ_NAME = "Asia/Shanghai"


def _fmt_ts(ts_ms: int) -> str:
    try:
        # interpret stored ms since epoch as UTC, convert to target TZ
        dt = datetime.utcfromtimestamp(ts_ms / 1000.0).replace(tzinfo=timezone.utc).astimezone(_TZ)
        return dt.strftime("%m-%d %H:%M")
    except Exception:
        try:
            dt = datetime.fromtimestamp(ts_ms / 1000.0)
            return dt.strftime("%m-%d %H:%M")
        except Exception:
            return "--"

# --- helper: fetch latest price from Binance (prefer futures) ---
def _fetch_latest_price(symbol: str) -> Optional[float]:
    urls = [
        f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}",
        f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}",
    ]
    for u in urls:
        try:
            with urllib.request.urlopen(u, timeout=2.5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode('utf-8'))
                    p = data.get('price')
                    if p is not None:
                        return float(p)
        except Exception:
            continue
    return None


# === New: compute realtime (forming bar) BOLL based on last window-1 closed + current latest close ===
def _get_strategy_status(db_path: str) -> Dict[str, Any]:
    """获取策略状态"""
    try:
        with _connect(db_path) as conn:
            cur = conn.execute(
                "SELECT position, pending, breakout_up, breakout_dn FROM strategy_state ORDER BY ts DESC LIMIT 1"
            )
            row = cur.fetchone()
            if row:
                position, pending, breakout_up, breakout_dn = row
                return {
                    "breakout_up": bool(breakout_up) if breakout_up is not None else False,
                    "breakout_dn": bool(breakout_dn) if breakout_dn is not None else False,
                    "status": pending if pending else "NONE"
                }
            return {
                "breakout_up": False,
                "breakout_dn": False,
                "status": "NONE"
            }
    except Exception:
        return {
            "breakout_up": False,
            "breakout_dn": False,
            "status": "NONE"
        }


def _get_realtime_boll(db_path: str, window: int, boll_multiplier: float, boll_ddof: int, symbol: Optional[str] = None) -> Dict[str, Any]:
    """
    计算实时BOLL：
    - 取最近 window-1 根已收盘K线的close
    - 加上“最新价格”作为当前形成中的K线close（若拉取失败则回退为数据库最新一条K线close）
    - 使用与Indicator一致的参数(boll_multiplier, ddof)
    返回的时间戳使用当前本地时间（毫秒），用于在UI显示读秒。
    """
    try:
        with _connect(db_path) as conn:
            # 最近 window-1 根已收盘K线
            cur1 = conn.execute(
                "SELECT close FROM klines WHERE is_closed=1 ORDER BY open_time DESC LIMIT ?",
                (max(0, window - 1),)
            )
            rows_closed = [float(r[0]) for r in cur1.fetchall()]
            rows_closed.reverse()  # 按时间正序

            # 最新价格（优先使用WS，其次REST，最后DB）
            last_close: Optional[float] = None
            source = "db"
            p_ws = _get_ws_price()
            if p_ws is not None:
                last_close = float(p_ws)
                source = "ws"
            elif symbol:
                p = _fetch_latest_price(symbol)
                if p is not None:
                    last_close = p
                    source = "exchange"

            if last_close is None:
                # 回退：数据库中最新一条K线（可能未收盘）的close
                cur2 = conn.execute(
                    "SELECT close FROM klines ORDER BY open_time DESC LIMIT 1"
                )
                r = cur2.fetchone()
                if r is None:
                    raise ValueError("no kline data")
                last_close = float(r[0])
                source = "db"

            closes = rows_closed + [last_close]
            if len(closes) < window:
                # 数据不足时不返回实时BOLL
                return {"ma": None, "std": None, "up": None, "dn": None, "timestamp": None, "time_local": None, "price": None, "source": None}

            # 计算
            if boll_ddof == 1:
                std_val = stats.stdev(closes)
            else:
                std_val = stats.pstdev(closes)
            ma_val = sum(closes) / len(closes)
            up_val = ma_val + boll_multiplier * std_val
            dn_val = ma_val - boll_multiplier * std_val

            now_ms = int(time.time() * 1000)
            return {
                "ma": round(ma_val, 2),
                "std": round(float(std_val), 4),
                "up": round(up_val, 2),
                "dn": round(dn_val, 2),
                "price": round(last_close, 2),
                "source": source,
                "timestamp": now_ms,
                "time_local": None  # 前端以本地时间动态展示读秒
            }
    except Exception:
        return {"ma": None, "std": None, "up": None, "dn": None, "timestamp": None, "time_local": None, "price": None, "source": None}


# New: globals for WS realtime price
_RT_PRICE_LOCK = threading.Lock()
_RT_PRICE: Dict[str, Any] = {"price": None, "ts": 0}
_WS_PRICE_THREAD: Optional[threading.Thread] = None


def _get_ws_price() -> Optional[float]:
    with _RT_PRICE_LOCK:
        return _RT_PRICE.get("price")


def _ensure_ws_price_feed(app: Flask) -> None:
    global _WS_PRICE_THREAD
    if _WS_PRICE_THREAD and _WS_PRICE_THREAD.is_alive():
        return
    c = app.config.get("SUMMARY_CFG", {})
    ws_base = c.get("ws_base") or "wss://fstream.binance.com"
    symbol = c.get("symbol") or "BTCUSDT"
    interval = c.get("interval") or "1m"
    ws_open_timeout = c.get("ws_open_timeout", 20)

    def _runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        client = WSClient(ws_base, symbol, interval, open_timeout=ws_open_timeout)

        async def on_kline(evt: KlineEvent):
            # Update forming bar close as realtime price
            with _RT_PRICE_LOCK:
                _RT_PRICE["price"] = float(evt.close)
                _RT_PRICE["ts"] = int(time.time() * 1000)
        try:
            loop.run_until_complete(client.connect_and_listen(on_kline))
        except asyncio.CancelledError:
            # Graceful shutdown of WS thread (e.g., process exiting)
            try:
                loop.stop()
            except Exception:
                pass
        except Exception:
            # On exit or error just stop loop
            try:
                loop.stop()
            except Exception:
                pass
        finally:
            try:
                loop.close()
            except Exception:
                pass

    t = threading.Thread(target=_runner, name="ws-price-feed", daemon=True)
    t.start()
    _WS_PRICE_THREAD = t
