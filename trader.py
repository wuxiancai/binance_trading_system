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
        """获取期货账户可用保证金余额"""
        try:
            # 使用futures_account获取账户信息，包含可用保证金
            account_info = self.client.futures_account(recvWindow=self.recv_window)
            # availableBalance是可用于开仓的保证金余额
            available_balance = float(account_info.get("availableBalance", 0.0))
            if available_balance > 0:
                return available_balance
            
            # 如果availableBalance不可用，回退到使用totalWalletBalance
            total_wallet_balance = float(account_info.get("totalWalletBalance", 0.0))
            if total_wallet_balance > 0:
                return total_wallet_balance
                
            # 最后回退到原来的方法
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
            # 获取仓位信息
            positions = self.client.futures_position_information(symbol=symbol, recvWindow=self.recv_window)
            # 获取账户信息以获取全仓保证金
            account_info = self.get_account_info()
            
            for pos in positions:
                if pos.get("symbol") == symbol:
                    position_amt = float(pos.get("positionAmt", 0))
                    if abs(position_amt) > 0.0001:  # 有仓位
                        entry_price = float(pos.get("entryPrice", 0))
                        mark_price = float(pos.get("markPrice", 0))
                        leverage = int(pos.get("leverage", 1))
                        
                        # 直接从API获取字段，不再计算
                        # 保证金余额 - 从账户信息获取全仓保证金
                        # 全仓保证金 = totalCrossWalletBalance (总全仓钱包余额)
                        margin_balance = float(account_info.get("totalCrossWalletBalance", 0))
                        # 如果没有全仓保证金信息，则使用仓位的逐仓保证金
                        if margin_balance == 0:
                            margin_balance = float(pos.get("isolatedMargin", 0))
                        
                        # 开仓金额 - 通过计算得出：开仓金额 = (数量 × 开仓价格) / 杠杆
                        # position_amt: 仓位数量, entry_price: 开仓价格, leverage: 杠杆倍数
                        position_initial_margin = (abs(position_amt) * entry_price) / leverage
                        
                        # 保证金比例 - 从账户信息获取保证金比例
                        # 保证金比例 = totalMaintMargin / totalCrossWalletBalance * 100
                        total_maint_margin = float(account_info.get("totalMaintMargin", 0))
                        total_cross_balance = float(account_info.get("totalCrossWalletBalance", 1))  # 避免除零
                        margin_ratio = (total_maint_margin / total_cross_balance * 100) if total_cross_balance > 0 else 0
                        
                        # 强平价格 - 从API直接获取
                        liquidation_price = float(pos.get("liquidationPrice", 0))
                        
                        # 盈亏 - 从API获取未实现盈亏
                        pnl = float(pos.get("unRealizedProfit", 0))
                        
                        # 盈亏回报率 - 从API获取回报率 (percentage)
                        pnl_percentage = float(pos.get("percentage", 0))
                        
                        # 数量 - 从API获取仓位数量 (绝对值)
                        quantity = abs(position_amt)
                        
                        # 合约显示 - 显示合约类型和杠杆倍数
                        # 从symbol提取基础货币对，添加永续标识和杠杆倍数
                        base_symbol = symbol.replace("USDT", "")  # 提取基础货币对，如BTC
                        margin_type = pos.get("marginType", "cross")  # 获取保证金类型
                        margin_type_cn = "全仓" if margin_type.lower() == "cross" else "逐仓"
                        contract = f"{base_symbol}USDT\n永续 {leverage}x"
                        
                        # 仓位价值
                        position_value = abs(position_amt) * mark_price
                        
                        return {
                            "symbol": symbol,
                            "contract": contract,  # 合约名称
                            "position_amt": position_amt,
                            "quantity": quantity,  # 数量 (绝对值)
                            "entry_price": entry_price,
                            "mark_price": mark_price,
                            "pnl": pnl,  # 盈亏 (USDT)
                            "pnl_percentage": pnl_percentage,  # 盈亏回报率 (%)
                            "position_side": "long" if position_amt > 0 else "short",
                            "leverage": leverage,
                            "margin_balance": margin_balance,  # 保证金余额 (USDT) - 从API获取全仓保证金
                            "position_initial_margin": position_initial_margin,  # 开仓金额 (USDT) - 从API获取初始保证金
                            "margin_ratio": margin_ratio,  # 保证金比例 (%) - 从API获取并正确转换
                            "liquidation_price": liquidation_price,  # 强平价格 - 从API获取
                            "position_value": position_value  # 仓位价值 (USDT)
                        }
            return None  # 无仓位
        except Exception as e:
            logging.warning(f"获取仓位信息失败: {e}")
            return None

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