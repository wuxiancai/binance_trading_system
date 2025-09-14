import logging
import math
import time
from typing import Optional

from binance.client import Client
from binance.enums import SIDE_BUY, SIDE_SELL, ORDER_TYPE_MARKET


class Trader:
    def __init__(self, api_key: Optional[str], api_secret: Optional[str], rest_base: str, use_testnet: bool,
                 recv_window: int = 5000, http_timeout: int = 30, qty_precision: int = 3,
                 price_round: int = 2, stop_loss_working_type: str = "CONTRACT_PRICE"):
        # python-binance 支持通过 timeout 配置 HTTP 超时
        self.client = Client(api_key, api_secret, tld='com', requests_params={'timeout': http_timeout/1.0})
        self.recv_window = recv_window
        self.qty_precision = qty_precision
        self.price_round = price_round
        self.stop_loss_working_type = stop_loss_working_type
        # Ensure FUTURES_URL points to the correct base including /fapi
        base = rest_base.rstrip('/')
        futures_base = f"{base}/fapi"
        # python-binance builds futures endpoints from FUTURES_URL
        self.client.FUTURES_URL = futures_base

    def apply_leverage(self, symbol: str, leverage: int):
        try:
            self.client.futures_change_leverage(symbol=symbol, leverage=leverage, recvWindow=self.recv_window)
        except Exception as e:
            logging.warning(f"change leverage failed: {e}")

    def get_balance_usdt(self) -> float:
        acct = self.client.futures_account_balance(recvWindow=self.recv_window)
        for b in acct:
            if b.get("asset") == "USDT":
                return float(b.get("withdrawAvailable", b.get("balance", 0.0)))
        return 0.0

    def _round_qty(self, qty: float) -> float:
        # 简单数量精度处理；生产建议根据 exchangeInfo 的 stepSize 动态对齐
        if qty <= 0:
            return 0.0
        factor = 10 ** self.qty_precision
        return max(1.0 / factor, math.floor(qty * factor) / factor)

    def calc_qty(self, symbol: str, price: float, max_position_pct: float) -> float:
        usdt = self.get_balance_usdt()
        usd_alloc = usdt * max_position_pct
        if price <= 0:
            return 0.0
        qty = usd_alloc / price
        return self._round_qty(qty)

    def place_market(self, symbol: str, side: str, qty: float):
        order = self.client.futures_create_order(
            symbol=symbol,
            side=side,
            type=ORDER_TYPE_MARKET,
            quantity=qty,
            reduceOnly=False,
            recvWindow=self.recv_window,
        )
        return order

    def close_position(self, symbol: str, side: str, qty: float):
        order = self.client.futures_create_order(
            symbol=symbol,
            side=side,
            type=ORDER_TYPE_MARKET,
            quantity=qty,
            reduceOnly=True,
            recvWindow=self.recv_window,
        )
        return order

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
                reduceOnly=True,
                workingType=self.stop_loss_working_type,
                recvWindow=self.recv_window,
            )
            return order
        except Exception as e:
            logging.warning(f"place stop loss failed: {e}")
            return None