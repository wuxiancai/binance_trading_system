import logging
import math
import time
from typing import Optional, Dict, Any

from binance.client import Client
from binance.enums import SIDE_BUY, SIDE_SELL, ORDER_TYPE_MARKET


class Trader:
    def __init__(self, api_key: Optional[str], api_secret: Optional[str], rest_base: str,
                 recv_window: int = 5000, http_timeout: int = 30, qty_precision: int = 3,
                 price_round: int = 2, stop_loss_working_type: str = "CONTRACT_PRICE"):
        # python-binance 支持通过 timeout 配置 HTTP 超时
        self.client = Client(api_key, api_secret, tld='com', requests_params={'timeout': http_timeout/1.0})
        self.recv_window = recv_window
        self.qty_precision = qty_precision  # 作为无过滤器时的回退精度
        self.price_round = price_round
        self.stop_loss_working_type = stop_loss_working_type
        # Ensure FUTURES_URL points to the correct base including /fapi
        base = rest_base.rstrip('/')
        futures_base = f"{base}/fapi"
        # python-binance builds futures endpoints from FUTURES_URL
        self.client.FUTURES_URL = futures_base
        # 符号过滤器缓存
        self._symbol_filters: Dict[str, Dict[str, Any]] = {}

    # ---------------------------
    # 符号过滤器/精度
    # ---------------------------
    def _ensure_symbol_filters(self, symbol: str):
        if symbol in self._symbol_filters:
            return
        try:
            info = self.client.futures_exchange_info()
            for s in info.get("symbols", []):
                if s.get("symbol") == symbol:
                    lot = {}
                    min_notional = None
                    for f in s.get("filters", []):
                        ftype = f.get("filterType")
                        if ftype == "LOT_SIZE":
                            lot = {
                                "stepSize": float(f.get("stepSize", 0)),
                                "minQty": float(f.get("minQty", 0)),
                                "maxQty": float(f.get("maxQty", 0)),
                            }
                        elif ftype == "MIN_NOTIONAL":
                            # Futures 使用 notional 最小值字段名可能为 notional
                            try:
                                min_notional = float(f.get("notional", 0))
                            except Exception:
                                # 兼容旧字段名
                                v = f.get("minNotional") or f.get("notional") or 0
                                min_notional = float(v)
                    self._symbol_filters[symbol] = {
                        "lot": lot,
                        "min_notional": min_notional,
                    }
                    return
            # 找不到符号则存放空过滤器（回退到qty_precision）
            self._symbol_filters[symbol] = {"lot": {}, "min_notional": None}
        except Exception as e:
            logging.warning(f"获取交易对过滤器失败 {symbol}: {e}")
            self._symbol_filters[symbol] = {"lot": {}, "min_notional": None}

    def _align_qty(self, symbol: str, qty: float) -> float:
        """根据 LOT_SIZE 的 stepSize/minQty 对齐数量，必要时回退到qty_precision。"""
        if qty <= 0:
            return 0.0
        self._ensure_symbol_filters(symbol)
        lot = self._symbol_filters.get(symbol, {}).get("lot", {})
        step = float(lot.get("stepSize", 0) or 0)
        min_qty = float(lot.get("minQty", 0) or 0)
        aligned = qty
        if step and step > 0:
            # 向下取整到步进
            aligned = math.floor(qty / step) * step
        else:
            # 回退到固定精度向下取整
            factor = 10 ** self.qty_precision
            aligned = math.floor(qty * factor) / factor
        # 确保不小于最小下单数量
        if min_qty and aligned < min_qty:
            aligned = 0.0  # 不足最小下单量时返回0，交由上层判断是否跳过
        # 避免浮点精度残留
        return float(f"{aligned:.10f}")

    # 兼容旧命名
    def _round_qty(self, symbol: str, qty: float) -> float:
        return self._align_qty(symbol, qty)

    def _ensure_min_notional(self, symbol: str, qty: float, price: float) -> float:
        """确保数量满足 MIN_NOTIONAL，如果不足则抬高到最小名义价值。"""
        if qty <= 0 or price <= 0:
            return 0.0
        self._ensure_symbol_filters(symbol)
        min_notional = self._symbol_filters.get(symbol, {}).get("min_notional")
        if not min_notional or min_notional <= 0:
            return qty
        notional = qty * price
        if notional >= min_notional:
            return qty
        # 提升到最小名义价值，再按步进对齐
        target_qty = min_notional / price
        return self._align_qty(symbol, target_qty)

    def apply_leverage(self, symbol: str, leverage: int):
        try:
            self.client.futures_change_leverage(symbol=symbol, leverage=leverage, recvWindow=self.recv_window)
        except Exception as e:
            logging.warning(f"change leverage failed: {e}")

    def get_balance_usdt(self) -> float:
        """获取期货账户可用保证金余额"""
        try:
            account_info = self.client.futures_account(recvWindow=self.recv_window)
            available_balance = float(account_info.get("availableBalance", 0.0))
            if available_balance > 0:
                return available_balance
            total_wallet_balance = float(account_info.get("totalWalletBalance", 0.0))
            if total_wallet_balance > 0:
                return total_wallet_balance
            acct = self.client.futures_account_balance(recvWindow=self.recv_window)
            for b in acct:
                if b.get("asset") == "USDT":
                    return float(b.get("balance", 0.0))
            return 0.0
        except Exception as e:
            logging.error(f"获取USDT余额失败: {e}")
            return 0.0

    def get_account_info(self) -> dict:
        """获取账户信息，包含全仓保证金等信息"""
        try:
            return self.client.futures_account(recvWindow=self.recv_window)
        except Exception as e:
            logging.error(f"获取账户信息失败: {e}")
            return {}

    def get_position_info(self, symbol: str) -> Optional[dict]:
        """获取指定交易对的仓位信息"""
        try:
            positions = self.client.futures_position_information(symbol=symbol, recvWindow=self.recv_window)
            account_info = self.get_account_info()
            for pos in positions:
                if pos.get("symbol") == symbol:
                    position_amt = float(pos.get("positionAmt", 0))
                    if abs(position_amt) > 0.0001:  # 有仓位
                        entry_price = float(pos.get("entryPrice", 0))
                        mark_price = float(pos.get("markPrice", 0))
                        leverage = int(pos.get("leverage", 1))
                        margin_balance = float(account_info.get("totalCrossWalletBalance", 0))
                        if margin_balance == 0:
                            margin_balance = float(pos.get("isolatedMargin", 0))
                        position_initial_margin = (abs(position_amt) * entry_price) / leverage
                        total_maint_margin = float(account_info.get("totalMaintMargin", 0))
                        total_cross_balance = float(account_info.get("totalCrossWalletBalance", 1))
                        margin_ratio = (total_maint_margin / total_cross_balance * 100) if total_cross_balance > 0 else 0
                        liquidation_price = float(pos.get("liquidationPrice", 0))
                        pnl = float(pos.get("unRealizedProfit", 0))
                        pnl_percentage = float(pos.get("percentage", 0))
                        quantity = abs(position_amt)
                        base_symbol = symbol.replace("USDT", "")
                        margin_type = pos.get("marginType", "cross")
                        margin_type_cn = "全仓" if margin_type.lower() == "cross" else "逐仓"
                        contract = f"{base_symbol}USDT\n永续 {leverage}x"
                        position_value = abs(position_amt) * mark_price
                        return {
                            "symbol": symbol,
                            "contract": contract,
                            "position_amt": position_amt,
                            "quantity": quantity,
                            "entry_price": entry_price,
                            "mark_price": mark_price,
                            "pnl": pnl,
                            "pnl_percentage": pnl_percentage,
                            "position_side": "long" if position_amt > 0 else "short",
                            "leverage": leverage,
                            "margin_balance": margin_balance,
                            "position_initial_margin": position_initial_margin,
                            "margin_ratio": margin_ratio,
                            "liquidation_price": liquidation_price,
                            "position_value": position_value
                        }
            return None
        except Exception as e:
            logging.warning(f"获取仓位信息失败: {e}")
            return None

    def calc_qty(self, symbol: str, price: float, max_position_pct: float) -> float:
        usdt = self.get_balance_usdt()
        usd_alloc = usdt * max_position_pct
        if price <= 0:
            return 0.0
        raw_qty = usd_alloc / price
        # 先确保最小名义价值，再按步进对齐
        qty = self._ensure_min_notional(symbol, raw_qty, price)
        qty = self._align_qty(symbol, qty)
        return qty

    def place_market(self, symbol: str, side: str, qty: float):
        aligned_qty = self._align_qty(symbol, qty)
        if aligned_qty <= 0:
            raise ValueError(f"下单数量不足最小步进/名义价值: {symbol} qty={qty}")
        order = self.client.futures_create_order(
            symbol=symbol,
            side=side,
            type=ORDER_TYPE_MARKET,
            quantity=aligned_qty,
            reduceOnly=False,
            recvWindow=self.recv_window,
        )
        return order

    def get_position_quantity(self, symbol: str) -> tuple[float, str]:
        """获取指定交易对的实际仓位数量和方向
        返回: (数量, 方向) 其中方向为 'long', 'short', 或 'flat'
        """
        try:
            positions = self.client.futures_position_information(symbol=symbol, recvWindow=self.recv_window)
            for pos in positions:
                if pos.get("symbol") == symbol:
                    position_amt = float(pos.get("positionAmt", 0))
                    if abs(position_amt) > 0.0001:  # 有仓位
                        if position_amt > 0:
                            return abs(position_amt), "long"
                        else:
                            return abs(position_amt), "short"
            return 0.0, "flat"
        except Exception as e:
            logging.error(f"获取仓位数量失败: {e}")
            return 0.0, "flat"

    def close_position(self, symbol: str, side: str, qty: float):
        """传统的平仓方法，使用指定数量"""
        aligned_qty = self._align_qty(symbol, qty)
        if aligned_qty <= 0:
            logging.info(f"{symbol} 平仓数量不足最小步进，跳过: qty={qty}")
            return None
        order = self.client.futures_create_order(
            symbol=symbol,
            side=side,
            type=ORDER_TYPE_MARKET,
            quantity=aligned_qty,
            reduceOnly=True,
            recvWindow=self.recv_window,
        )
        return order

    def close_all_position(self, symbol: str):
        """市价全部平仓 - 获取实际仓位数量并完全平仓"""
        try:
            qty, direction = self.get_position_quantity(symbol)
            if direction == "flat" or qty == 0:
                logging.info(f"{symbol} 没有持仓，无需平仓")
                return None
            if direction == "long":
                side = SIDE_SELL
            else:
                side = SIDE_BUY
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type=ORDER_TYPE_MARKET,
                quantity=self._round_qty(symbol, qty),
                reduceOnly=True,
                recvWindow=self.recv_window,
            )
            logging.info(f"市价全部平仓成功: {symbol} {direction} {qty}")
            return order
        except Exception as e:
            logging.error(f"市价全部平仓失败: {e}")
            return None

    def close_all_position_with_stop_market(self, symbol: str):
        """使用STOP_MARKET + closePosition=true 立即全部平仓"""
        try:
            qty, direction = self.get_position_quantity(symbol)
            if direction == "flat" or qty == 0:
                logging.info(f"{symbol} 没有持仓，无需平仓")
                return None
            ticker = self.client.futures_symbol_ticker(symbol=symbol)
            current_price = float(ticker['price'])
            if direction == "long":
                side = SIDE_SELL
                stop_price = round(current_price * 0.999, self.price_round)
            else:
                side = SIDE_BUY
                stop_price = round(current_price * 1.001, self.price_round)
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type="STOP_MARKET",
                stopPrice=stop_price,
                closePosition=True,
                workingType=self.stop_loss_working_type,
                recvWindow=self.recv_window,
            )
            logging.info(f"STOP_MARKET全部平仓成功: {symbol} {direction}")
            return order
        except Exception as e:
            logging.error(f"STOP_MARKET全部平仓失败: {e}")
            return self.close_all_position(symbol)

    def place_stop_loss(self, symbol: str, position: str, entry_price: float, stop_loss_pct: float):
        """Place a reduce-only STOP_MARKET order at +/- stop_loss_pct from entry.
        position: 'long' or 'short'
        """
        try:
            if position == "long":
                stop_price = entry_price * (1 - stop_loss_pct)
                side = SIDE_SELL
            elif position == "short":
                stop_price = entry_price * (1 + stop_loss_pct)
                side = SIDE_BUY
            else:
                return None
            stop_price = round(stop_price, self.price_round)
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type="STOP_MARKET",
                stopPrice=stop_price,
                closePosition=True,
                workingType=self.stop_loss_working_type,
                recvWindow=self.recv_window,
            )
            return order
        except Exception as e:
            logging.warning(f"place stop loss failed: {e}")
            return None