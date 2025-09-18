from dataclasses import dataclass

@dataclass
class StrategyState:
    position: str = "flat"  # flat | long | short
    pending: str | None = None  # waiting_short_entry | waiting_long_entry | waiting_short_confirm | waiting_long_confirm
    entry_price: float | None = None  # 开仓价格，用于止损计算
    breakout_level: float | None = None  # 最近一次突破时的关键价位（上轨或下轨），用于提示/记录

    def load_from_dict(self, state_dict):
        """从字典加载状态"""
        if state_dict:
            self.position = state_dict.get('position', 'flat')
            self.pending = state_dict.get('pending')
            self.entry_price = state_dict.get('entry_price')
            self.breakout_level = state_dict.get('breakout_level')

    def to_dict(self):
        """转换为字典用于保存"""
        return {
            'position': self.position,
            'pending': self.pending,
            'entry_price': self.entry_price,
            'breakout_level': self.breakout_level
        }


def decide(price: float, up: float, dn: float, state: StrategyState) -> str | None:
    """
    基于布林带的突破回调策略
    
    策略逻辑：
    1. 价格突破上轨 -> 等待回调到上轨 -> 开空仓
    2. 价格突破下轨 -> 等待反弹到下轨 -> 开多仓
    3. 持仓期间，价格再次突破对应轨道则止损
    """
    
    # 检查关键参数是否为None，避免TypeError
    if up is None or dn is None:
        return None
    
    # 1) 即刻止损（使用当前上下轨判断，不依赖breakout_level，确保在等待确认阶段也能触发）
    if state.position == "short":
        if price > up:  # 价格再次站上上轨，空仓止损
            state.position = "flat"
            state.pending = None
            state.entry_price = None
            state.breakout_level = None
            return "stop_loss_short"
    elif state.position == "long":
        if price < dn:  # 价格再次跌破下轨，多仓止损
            state.position = "flat"
            state.pending = None
            state.entry_price = None
            state.breakout_level = None
            return "stop_loss_long"
    
    # 2) 首次开仓逻辑（flat）
    if state.position == "flat":
        # 记录突破并等待回调/反弹
        if price > up and state.pending != "waiting_short_entry":
            state.pending = "waiting_short_entry"
            state.breakout_level = up
            return None
        if price < dn and state.pending != "waiting_long_entry":
            state.pending = "waiting_long_entry"
            state.breakout_level = dn
            return None

        # 回调/反弹到轨道触发开仓
        if state.pending == "waiting_short_entry" and price <= up:
            state.position = "short"
            state.pending = None
            state.entry_price = price
            # breakout_level 保留为上轨，便于UI展示
            return "open_short"
        if state.pending == "waiting_long_entry" and price >= dn:
            state.position = "long"
            state.pending = None
            state.entry_price = price
            # breakout_level 保留为下轨，便于UI展示
            return "open_long"

    # 3) 持仓后的翻转逻辑
    elif state.position == "short":
        # 跌破下轨后等待反弹确认
        if price < dn and state.pending != "waiting_long_confirm":
            state.pending = "waiting_long_confirm"
            # breakout_level 更新为下轨，仅作为记录展示
            state.breakout_level = dn
            return None
        if state.pending == "waiting_long_confirm" and price >= dn:
            state.position = "long"
            state.pending = None
            state.entry_price = price
            return "close_short_open_long"

    elif state.position == "long":
        # 突破上轨后等待回调确认
        if price > up and state.pending != "waiting_short_confirm":
            state.pending = "waiting_short_confirm"
            # breakout_level 更新为上轨，仅作为记录展示
            state.breakout_level = up
            return None
        if state.pending == "waiting_short_confirm" and price <= up:
            state.position = "short"
            state.pending = None
            state.entry_price = price
            return "close_long_open_short"

    return None