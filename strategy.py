from dataclasses import dataclass

@dataclass
class StrategyState:
    position: str = "flat"  # flat | long | short
    pending: str | None = None  # waiting_short_entry | waiting_long_entry | waiting_short_confirm | waiting_long_confirm
    entry_price: float | None = None  # 开仓价格，用于止损计算
    breakout_level: float | None = None  # 突破的关键价位（上轨或下轨）


def decide(price: float, up: float, dn: float, state: StrategyState) -> str | None:
    """
    新的回调确认策略：
    1. 价格突破BOLL上轨后，回落到上轨价格时 → 开仓做空，如果再次突破上轨则止损
    2. 价格跌破BOLL下轨后，反弹到下轨价格以上时 → 平空仓+开多仓，如果再次跌破下轨，止损多仓
    3. 价格突破BOLL上轨后，回落到上轨价格时 → 平多仓+开空仓
    4. 如此循环，始终保持仓位
    """
    
    # 处理止损情况
    if state.position == "short" and state.entry_price and state.breakout_level:
        # 空仓止损：价格再次突破上轨（breakout_level应该是上轨）
        if price > state.breakout_level and state.breakout_level == up:
            state.position = "flat"
            state.pending = None
            state.entry_price = None
            state.breakout_level = None
            return "stop_loss_short"
    
    if state.position == "long" and state.entry_price and state.breakout_level:
        # 多仓止损：价格再次跌破下轨（breakout_level应该是下轨）
        if price < state.breakout_level and state.breakout_level == dn:
            state.position = "flat"
            state.pending = None
            state.entry_price = None
            state.breakout_level = None
            return "stop_loss_long"
    
    # 首次开仓逻辑（从flat状态开始）
    if state.position == "flat":
        # 检测突破上轨，等待回调开空
        if price > up and state.pending != "waiting_short_entry":
            state.pending = "waiting_short_entry"
            state.breakout_level = up
            return None
        
        # 检测跌破下轨，等待反弹开多
        if price < dn and state.pending != "waiting_long_entry":
            state.pending = "waiting_long_entry"
            state.breakout_level = dn
            return None
        
        # 突破上轨后回落到上轨，开空仓
        if state.pending == "waiting_short_entry" and price <= up:
            state.position = "short"
            state.pending = None
            state.entry_price = price
            # breakout_level保持为up，用于止损判断
            return "open_short"
        
        # 跌破下轨后反弹到下轨以上，开多仓
        if state.pending == "waiting_long_entry" and price >= dn:
            state.position = "long"
            state.pending = None
            state.entry_price = price
            # breakout_level保持为dn，用于止损判断
            return "open_long"
    
    # 持仓状态下的平仓+开仓逻辑
    elif state.position == "short":
        # 空仓状态下，检测跌破下轨，等待反弹平空开多
        if price < dn and state.pending != "waiting_long_confirm":
            state.pending = "waiting_long_confirm"
            state.breakout_level = dn  # 更新为下轨，用于多仓止损
            return None
        
        # 跌破下轨后反弹到下轨以上，平空开多
        if state.pending == "waiting_long_confirm" and price >= dn:
            state.position = "long"
            state.pending = None
            state.entry_price = price
            return "close_short_open_long"
    
    elif state.position == "long":
        # 多仓状态下，检测突破上轨，等待回落平多开空
        if price > up and state.pending != "waiting_short_confirm":
            state.pending = "waiting_short_confirm"
            state.breakout_level = up  # 更新为上轨，用于空仓止损
            return None
        
        # 突破上轨后回落到上轨，平多开空
        if state.pending == "waiting_short_confirm" and price <= up:
            state.position = "short"
            state.pending = None
            state.entry_price = price
            return "close_long_open_short"
    
    return None