import threading
import subprocess
import sqlite3
import json
import socket
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Optional, Dict, Any, List, Tuple

from flask import Flask, jsonify, Response, request


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


def _recent_errors(db_path: str, limit: int = 20) -> List[Dict[str, Any]]:
    with _connect(db_path) as conn:
        cur = conn.execute(
            "SELECT ts, where_, error FROM errors ORDER BY ts DESC LIMIT ?", (limit,)
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
        for r in rows:
            r["ts_local"] = _fmt_ts(r["ts"])
        return rows


def _compute_current_position(db_path: str) -> Dict[str, Any]:
    """Derive current position from latest trades.
    Heuristic:
      - Latest BUY or BUY_OPEN -> long
      - Latest SELL or SELL_OPEN -> short
      - Latest *_CLOSE with no later OPEN -> flat
    """
    with _connect(db_path) as conn:
        cur = conn.execute(
            "SELECT ts, side, qty, price FROM trades ORDER BY ts DESC LIMIT 200"
        )
        for row in cur.fetchall():
            side = row["side"]
            if side in ("BUY", "BUY_OPEN"):
                return {
                    "position": "long",
                    "entry_price": row["price"],
                    "qty": row["qty"],
                    "ts": row["ts"],
                    "ts_local": _fmt_ts(row["ts"]),
                }
            if side in ("SELL", "SELL_OPEN"):
                return {
                    "position": "short",
                    "entry_price": row["price"],
                    "qty": row["qty"],
                    "ts": row["ts"],
                    "ts_local": _fmt_ts(row["ts"]),
                }
            if side in ("BUY_CLOSE", "SELL_CLOSE"):
                return {"position": "flat"}
        return {"position": "unknown"}


def _compute_last_closed_pnl(db_path: str) -> Optional[Dict[str, Any]]:
    """Find the latest *_CLOSE trade and pair it with its previous OPEN to compute realized PnL."""
    with _connect(db_path) as conn:
        # latest close
        cur = conn.execute(
            "SELECT ts, side, qty, price FROM trades WHERE side IN ('BUY_CLOSE','SELL_CLOSE') ORDER BY ts DESC LIMIT 1"
        )
        last_close = cur.fetchone()
        if not last_close:
            return None
        close_side = last_close["side"]
        close_ts = last_close["ts"]
        close_price = float(last_close["price"]) if last_close["price"] is not None else None
        qty = float(last_close["qty"]) if last_close["qty"] is not None else 0.0

        if close_side == "SELL_CLOSE":
            # long closed; find preceding BUY/BUY_OPEN before close_ts
            cur = conn.execute(
                "SELECT ts, price, qty FROM trades WHERE ts <= ? AND side IN ('BUY','BUY_OPEN') ORDER BY ts DESC LIMIT 1",
                (close_ts,),
            )
            open_row = cur.fetchone()
            if not open_row or close_price is None:
                return None
            open_price = float(open_row["price"]) if open_row["price"] is not None else None
            if open_price is None:
                return None
            pnl = (close_price - open_price) * qty
            return {
                "side": "long",
                "entry_price": open_price,
                "exit_price": close_price,
                "qty": qty,
                "pnl": pnl,
                "open_time": open_row["ts"],
                "open_time_local": _fmt_ts(open_row["ts"]),
                "close_time": close_ts,
                "close_time_local": _fmt_ts(close_ts),
            }
        else:  # BUY_CLOSE => short closed
            cur = conn.execute(
                "SELECT ts, price, qty FROM trades WHERE ts <= ? AND side IN ('SELL','SELL_OPEN') ORDER BY ts DESC LIMIT 1",
                (close_ts,),
            )
            open_row = cur.fetchone()
            if not open_row or close_price is None:
                return None
            open_price = float(open_row["price"]) if open_row["price"] is not None else None
            if open_price is None:
                return None
            pnl = (open_price - close_price) * qty
            return {
                "side": "short",
                "entry_price": open_price,
                "exit_price": close_price,
                "qty": qty,
                "pnl": pnl,
                "open_time": open_row["ts"],
                "open_time_local": _fmt_ts(open_row["ts"]),
                "close_time": close_ts,
                "close_time_local": _fmt_ts(close_ts),
            }


def _latest_price(db_path: str) -> Optional[float]:
    try:
        with _connect(db_path) as conn:
            cur = conn.execute("SELECT close FROM klines ORDER BY close_time DESC LIMIT 1")
            row = cur.fetchone()
            if row and (row["close"] is not None):
                return float(row["close"])
    except Exception:
        pass
    return None


def _get_pnl_records(db_path: str, limit: int = 20) -> List[Dict[str, Any]]:
    """获取所有平仓交易的盈亏记录"""
    records = []
    with _connect(db_path) as conn:
        # 获取所有平仓交易
        cur = conn.execute(
            "SELECT ts, side, qty, price FROM trades WHERE side IN ('BUY_CLOSE','SELL_CLOSE') ORDER BY ts DESC LIMIT ?",
            (limit,)
        )
        close_trades = cur.fetchall()
        
        for close_trade in close_trades:
            close_side = close_trade["side"]
            close_ts = close_trade["ts"]
            close_price = float(close_trade["price"]) if close_trade["price"] is not None else None
            qty = float(close_trade["qty"]) if close_trade["qty"] is not None else 0.0
            
            if close_price is None:
                continue
                
            if close_side == "SELL_CLOSE":
                # 多仓平仓，找前面的开多仓
                cur2 = conn.execute(
                    "SELECT ts, price FROM trades WHERE ts <= ? AND side IN ('BUY','BUY_OPEN') ORDER BY ts DESC LIMIT 1",
                    (close_ts,)
                )
                open_row = cur2.fetchone()
                if open_row and open_row["price"] is not None:
                    open_price = float(open_row["price"])
                    pnl = (close_price - open_price) * qty
                    records.append({
                        "ts": close_ts,
                        "ts_local": _fmt_ts(close_ts),
                        "side": "long",
                        "entry_price": open_price,
                        "exit_price": close_price,
                        "qty": qty,
                        "pnl": pnl
                    })
            else:  # BUY_CLOSE
                # 空仓平仓，找前面的开空仓
                cur2 = conn.execute(
                    "SELECT ts, price FROM trades WHERE ts <= ? AND side IN ('SELL','SELL_OPEN') ORDER BY ts DESC LIMIT 1",
                    (close_ts,)
                )
                open_row = cur2.fetchone()
                if open_row and open_row["price"] is not None:
                    open_price = float(open_row["price"])
                    pnl = (open_price - close_price) * qty
                    records.append({
                        "ts": close_ts,
                        "ts_local": _fmt_ts(close_ts),
                        "side": "short",
                        "entry_price": open_price,
                        "exit_price": close_price,
                        "qty": qty,
                        "pnl": pnl
                    })
    return records


def _get_daily_stats(db_path: str, days: int = 7) -> List[Dict[str, Any]]:
    """获取每日交易统计"""
    stats = []
    with _connect(db_path) as conn:
        # 获取最近几天的平仓交易
        cur = conn.execute(
            "SELECT ts, side, qty, price FROM trades WHERE side IN ('BUY_CLOSE','SELL_CLOSE') ORDER BY ts DESC"
        )
        close_trades = cur.fetchall()
        
        # 按日期分组统计
        daily_data = {}
        
        for close_trade in close_trades:
            close_side = close_trade["side"]
            close_ts = close_trade["ts"]
            close_price = float(close_trade["price"]) if close_trade["price"] is not None else None
            qty = float(close_trade["qty"]) if close_trade["qty"] is not None else 0.0
            
            if close_price is None:
                continue
                
            # 获取日期
            date_str = _fmt_ts(close_ts).split(' ')[0]  # 只取日期部分
            
            if date_str not in daily_data:
                daily_data[date_str] = {'trades': 0, 'total_pnl': 0.0}
            
            # 计算盈亏
            pnl = 0.0
            if close_side == "SELL_CLOSE":
                # 多仓平仓
                cur2 = conn.execute(
                    "SELECT price FROM trades WHERE ts <= ? AND side IN ('BUY','BUY_OPEN') ORDER BY ts DESC LIMIT 1",
                    (close_ts,)
                )
                open_row = cur2.fetchone()
                if open_row and open_row["price"] is not None:
                    open_price = float(open_row["price"])
                    pnl = (close_price - open_price) * qty
            else:  # BUY_CLOSE
                # 空仓平仓
                cur2 = conn.execute(
                    "SELECT price FROM trades WHERE ts <= ? AND side IN ('SELL','SELL_OPEN') ORDER BY ts DESC LIMIT 1",
                    (close_ts,)
                )
                open_row = cur2.fetchone()
                if open_row and open_row["price"] is not None:
                    open_price = float(open_row["price"])
                    pnl = (open_price - close_price) * qty
            
            daily_data[date_str]['trades'] += 1
            daily_data[date_str]['total_pnl'] += pnl
        
        # 转换为列表并计算利润率
        for date_str, data in sorted(daily_data.items(), reverse=True)[:days]:
            profit_rate = 0.0
            if data['trades'] > 0:
                # 简单的利润率计算（假设每笔交易投入相同）
                profit_rate = (data['total_pnl'] / data['trades']) * 100 if data['trades'] > 0 else 0.0
            
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
        "use_testnet": getattr(cfg, "use_testnet", None),
        "leverage": getattr(cfg, "leverage", None),
        "max_position_pct": getattr(cfg, "max_position_pct", None),
        "window": getattr(cfg, "window", None),
        "only_on_close": getattr(cfg, "only_on_close", None),
        "stop_loss_enabled": getattr(cfg, "stop_loss_enabled", None),
        "stop_loss_pct": getattr(cfg, "stop_loss_pct", None),
        "tz": getattr(cfg, "tz", None),
        "log_level": getattr(cfg, "log_level", None),
        "db_path": getattr(cfg, "db_path", "trader.db"),
    }

    @app.get("/api/summary")
    def api_summary() -> Response:
        c = app.config["SUMMARY_CFG"]
        db_path = c["db_path"]
        position = _compute_current_position(db_path)
        last_closed = _compute_last_closed_pnl(db_path)
        signals = _recent_signals(db_path, limit=20)
        trades = _recent_trades(db_path, limit=20)
        errors = _recent_errors(db_path, limit=10)
        pnl_records = _get_pnl_records(db_path, limit=20)
        daily_stats = _get_daily_stats(db_path, days=7)
        # enrich position with leverage
        if position.get("position") in ("long", "short"):
            position["leverage"] = c["leverage"]
        return jsonify({
            "config": {**c, "web_port": app.config.get("WEB_PORT", 5000)},
            "position": position,
            "last_closed": last_closed,
            "signals": signals,
            "trades": trades,
            "errors": errors,
            "pnl_records": pnl_records,
            "daily_stats": daily_stats,
        })

    @app.post("/api/test_order")
    def api_test_order() -> Response:
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
                 .container{ max-width: 1600px; margin: 0 auto; padding: 16px 12px; }
                 .header{ 
                   display:flex; align-items:center; justify-content:space-between; 
                   margin-bottom: 20px; padding: 16px 20px; background: rgba(255,255,255,0.95); 
                   border-radius: 12px; box-shadow: var(--shadow);
                 }
                 .btn{ 
                   appearance:none; border:2px solid var(--accent); background:var(--accent); color:white; 
                   padding:8px 16px; border-radius:8px; cursor:pointer; font-size:13px; font-weight:600;
                   transition: all 0.2s ease; text-transform: uppercase; letter-spacing: 0.3px;
                 }
                 .btn:hover{ transform: translateY(-1px); box-shadow: var(--shadow-lg); }
                 .btn.warn{ border-color:var(--danger); background:var(--danger); }
                 .btn.warn:hover{ background:#dc2626; }
                 h1 { margin: 0; font-size: 24px; font-weight: 700; color: var(--fg); letter-spacing: -0.3px; }
                 small { color: var(--muted); }
                 .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); gap: 16px; align-items:start; max-width: 1600px; margin-left: auto; margin-right: auto; }
                 .card { 
                   background:var(--card); border: 1px solid var(--border); border-radius: 12px; 
                   padding: 16px; box-shadow: var(--shadow); transition: all 0.2s ease;
                 }
                 .card:hover { transform: translateY(-2px); box-shadow: var(--shadow-lg); }
                 .card h3{ margin: 0 0 12px; font-size: 16px; font-weight: 600; color: var(--fg); }
                 .table-wrap{ max-height: 350px; overflow:auto; border-radius: 6px; }
                 table { width: 100%; border-collapse: collapse; table-layout: fixed; }
                 th, td { 
                   border-bottom: 1px solid var(--border); padding: 8px 6px; text-align: left; 
                   white-space: nowrap; overflow:hidden; text-overflow: ellipsis; font-size: 13px; 
                   line-height: 1.4;
                 }
                 th { 
                   position: sticky; top: 0; background: var(--thead); z-index: 1; 
                   font-weight: 600; color: var(--fg); text-transform: uppercase; 
                   font-size: 11px; letter-spacing: 0.3px; padding: 6px;
                 }
                 .ok { color: var(--success); font-weight: 600; }
                 .warn { color: var(--warning); font-weight: 600; }
                 .err { color: var(--danger); font-weight: 600; }
                 .dir-long { color: var(--success); font-weight: 600; font-size: 12px; }
                 .dir-short { color: var(--danger); font-weight: 600; font-size: 12px; }
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
                <div>
                  <button class="btn" onclick="testOrder('BUY')">测试买入</button>
                  <button class="btn warn" onclick="testOrder('SELL')">测试卖出</button>
                </div>
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
                 async function testOrder(side){
                     try{
                        const res = await fetch('/api/test_order', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({side, percent: 0.01})});
                        const data = await res.json();
                        if(!res.ok || !data.ok){
                           alert('下单失败: ' + (data.error || res.statusText));
                           return;
                        }
                        alert(`下单成功: ${data.side} qty=${data.qty} price=${data.price}`);
                        load();
                     }catch(err){
                        alert('请求失败: ' + err);
                     }
                 }

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
                           <tr><th>Symbol</th><td>${cfg.symbol}</td></tr>
                           <tr><th>Interval</th><td>${cfg.interval}</td></tr>
                           <tr><th>Testnet</th><td>${boolCell(cfg.use_testnet)}</td></tr>
                           <tr><th>Leverage</th><td>${cfg.leverage}</td></tr>
                           <tr><th>Max Position %</th><td>${cfg.max_position_pct}</td></tr>
                           <tr><th>Window</th><td>${cfg.window}</td></tr>
                           <tr><th>Only On Close</th><td>${boolCell(cfg.only_on_close)}</td></tr>
                           <tr><th>Stop Loss</th><td>${boolCell(cfg.stop_loss_enabled)} (pct=${cfg.stop_loss_pct})</td></tr>
                           <tr><th>TZ</th><td>${cfg.tz}</td></tr>
                           <tr><th>Log</th><td>${cfg.log_level}</td></tr>
                           <tr><th>Web Port</th><td>${cfg.web_port}</td></tr>
                         </table>
                     </div>`);
 
                     // Position (render before trades)
                     const p = data.position || {};
                     if (p.position === 'long' || p.position === 'short') {
                      const amount = (p.entry_price != null && p.qty != null) ? (Number(p.entry_price) * Number(p.qty)) : null;
                      cards.push(`
                        <div class="card">
                          <h3>当前仓位</h3>
                          <table>
                            <tr><th>方向</th><td><span class="${dirClass(p.position)}">${fmt(p.position, 0)}</span></td></tr>
                            <tr><th>买入价格</th><td>${fmt(p.entry_price)}</td></tr>
                            <tr><th>数量</th><td>${fmt(p.qty, 4)}</td></tr>
                            <tr><th>金额</th><td>${fmt(amount)}</td></tr>
                            <tr><th>杠杆</th><td>${fmt(p.leverage, 0)}</td></tr>
                            <tr><th>建仓时间</th><td>${p.ts_local ?? dash}</td></tr>
                          </table>
                        </div>`);
                     } else {
                      cards.push(`
                        <div class="card">
                          <h3>当前仓位</h3>
                          <table>
                            <tr><th>方向</th><td>${dash}</td></tr>
                            <tr><th>买入价格</th><td>${dash}</td></tr>
                            <tr><th>数量</th><td>${dash}</td></tr>
                            <tr><th>金额</th><td>${dash}</td></tr>
                            <tr><th>杠杆</th><td>${dash}</td></tr>
                            <tr><th>建仓时间</th><td>${dash}</td></tr>
                          </table>
                        </div>`);
                     }

                     // PnL function for trades table
                     const pnlClass = (pnl) => {
                       if (pnl == null) return '';
                       return Number(pnl) >= 0 ? 'pnl-profit' : 'pnl-loss';
                     };

                     // Daily Stats
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
 
                     // Recent trades (placed after position, before signals)
                    const statusClass = (status) => {
                      if (!status) return '';
                      const s = String(status).toUpperCase();
                      if (s === 'NEW') return 'status-new';
                      if (s === 'OVER') return 'status-over';
                      return '';
                    };
                    
                    // Calculate PnL for each trade
                    const tradesWithPnl = (data.trades || []).map((t, index) => {
                      let pnl = null;
                      // Find matching PnL record for this trade
                      const pnlRecord = (data.pnl_records || []).find(p => 
                        Math.abs(new Date(p.ts_local).getTime() - new Date(t.ts_local).getTime()) < 60000 && // within 1 minute
                        ((t.side.includes('CLOSE') && p.side === (t.side.includes('BUY') ? 'short' : 'long')))
                      );
                      if (pnlRecord) {
                        pnl = pnlRecord.pnl;
                      }
                      return {...t, pnl};
                    });
                    
                    const tdRows = tradesWithPnl.map(t => `<tr><td>${t.ts_local}</td><td><span class="${dirClass(t.side)}">${t.side}</span></td><td>${t.qty}</td><td>${t.price ?? ''}</td><td><span class="${statusClass(t.status)}">${t.status ?? ''}</span></td><td>${t.pnl != null ? `<span class="${pnlClass(t.pnl)}">${fmt(t.pnl)}</span>` : '--'}</td><td>${t.order_id ?? ''}</td></tr>`).join('');
                     cards.push(`
                       <div class="card">
                         <h3>最近交易</h3>
                        <div class="table-wrap">
                          <table>
                            <tr><th style="width:18%">时间</th><th style="width:8%">方向</th><th style="width:10%">数量</th><th style="width:12%">价格</th><th style="width:8%">状态</th><th style="width:12%">盈亏</th><th style="width:32%">订单ID</th></tr>
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
 
 

 
                     // Recent errors
                    const errRows = (data.errors || []).map(e => `<tr><td>${e.ts_local}</td><td>${e.error}</td></tr>`).join('');
                     cards.push(`
                       <div class="card">
                         <h3>最近错误</h3>
                        <div class="table-wrap">
                          <table>
                            <tr><th style="width:35%">时间</th><th style="width:65%">错误</th></tr>
                            ${errRows}
                          </table>
                        </div>
                       </div>`);
 
                     document.getElementById('cards').innerHTML = cards.join('');
                 }
                 load();
                 setInterval(load, 3000);
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