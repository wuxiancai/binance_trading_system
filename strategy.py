from dataclasses import dataclass

@dataclass
class StrategyState:
    position: str = "flat"  # flat | long | short
    pending: str | None = None  # waiting_short_entry | waiting_long_entry | waiting_short_confirm | waiting_long_confirm
    entry_price: float | None = None  # 开仓价格，用于止损计算
    breakout_level: float | None = None  # 最近一次突破时的关键价位（上轨或下轨），用于提示/记录
    # 新增突破状态跟踪
    breakout_up: bool = False  # 是否突破上轨
    breakout_dn: bool = False  # 是否跌破下轨
    last_close_price: float | None = None  # 上一根K线收盘价，用于判断突破

    def load_from_dict(self, state_dict):
        """从字典加载状态"""
        if state_dict:
            self.position = state_dict.get('position', 'flat')
            self.pending = state_dict.get('pending')
            self.entry_price = state_dict.get('entry_price')
            self.breakout_level = state_dict.get('breakout_level')
            self.breakout_up = state_dict.get('breakout_up', False)
            self.breakout_dn = state_dict.get('breakout_dn', False)
            self.last_close_price = state_dict.get('last_close_price')

    def to_dict(self):
        """转换为字典用于保存"""
        return {
            'position': self.position,
            'pending': self.pending,
            'entry_price': self.entry_price,
            'breakout_level': self.breakout_level,
            'breakout_up': self.breakout_up,
            'breakout_dn': self.breakout_dn,
            'last_close_price': self.last_close_price
        }


def decide(close_price: float, up: float, dn: float, state: StrategyState) -> str | None:
    """
    基于布林带的突破回调策略（基于K线收盘价）
    
    策略逻辑：
    1. K线收盘价突破上轨 -> 设置waiting_short_entry -> K线收盘价回调到上轨以下 -> 开空仓
    2. K线收盘价跌破下轨 -> 设置waiting_long_entry -> K线收盘价反弹到下轨以上 -> 开多仓
    3. 持仓期间，价格再次突破对应轨道则止损
    """
    
    # 检查关键参数是否为None，避免TypeError
    if up is None or dn is None:
        return None
    
    # 更新突破状态（基于收盘价）
    if state.last_close_price is not None:
        # 检查是否突破上轨（收盘价从上轨以下突破到上轨以上）
        if state.last_close_price <= up and close_price > up:
            state.breakout_up = True
            state.breakout_dn = False  # 重置下轨突破状态
        # 检查是否跌破下轨（收盘价从下轨以上跌破到下轨以下）
        elif state.last_close_price >= dn and close_price < dn:
            state.breakout_dn = True
            state.breakout_up = False  # 重置上轨突破状态
        # 如果价格回到轨道内，重置突破状态
        elif close_price <= up and close_price >= dn:
            state.breakout_up = False
            state.breakout_dn = False
    
    # 更新上一根K线收盘价
    state.last_close_price = close_price
    
    # 1) 即刻止损（使用当前上下轨判断）
    if state.position == "short":
        if close_price > up:  # 收盘价再次站上上轨，空仓止损
            state.position = "flat"
            state.pending = None
            state.entry_price = None
            state.breakout_level = None
            state.breakout_up = False
            state.breakout_dn = False
            return "stop_loss_short"
    elif state.position == "long":
        if close_price < dn:  # 收盘价再次跌破下轨，多仓止损
            state.position = "flat"
            state.pending = None
            state.entry_price = None
            state.breakout_level = None
            state.breakout_up = False
            state.breakout_dn = False
            return "stop_loss_long"
    
    # 2) 首次开仓逻辑（flat）
    if state.position == "flat":
        # 突破上轨，设置等待开空仓状态
        if state.breakout_up and state.pending != "waiting_short_entry":
            state.pending = "waiting_short_entry"
            state.breakout_level = up
            return None
        # 跌破下轨，设置等待开多仓状态
        if state.breakout_dn and state.pending != "waiting_long_entry":
            state.pending = "waiting_long_entry"
            state.breakout_level = dn
            return None

        # 回调到上轨以下，开空仓
        if state.pending == "waiting_short_entry" and close_price <= up:
            state.position = "short"
            state.pending = None
            state.entry_price = close_price
            state.breakout_up = False  # 重置突破状态
            return "open_short"
        # 反弹到下轨以上，开多仓
        if state.pending == "waiting_long_entry" and close_price >= dn:
            state.position = "long"
            state.pending = None
            state.entry_price = close_price
            state.breakout_dn = False  # 重置突破状态
            return "open_long"

    # 3) 持仓后的翻转逻辑
    elif state.position == "short":
        # 跌破下轨后等待反弹确认
        if state.breakout_dn and state.pending != "waiting_long_confirm":
            state.pending = "waiting_long_confirm"
            state.breakout_level = dn
            return None
        if state.pending == "waiting_long_confirm" and close_price >= dn:
            state.position = "long"
            state.pending = None
            state.entry_price = close_price
            state.breakout_dn = False  # 重置突破状态
            return "close_short_open_long"

    elif state.position == "long":
        # 突破上轨后等待回调确认
        if state.breakout_up and state.pending != "waiting_short_confirm":
            state.pending = "waiting_short_confirm"
            state.breakout_level = up
            return None
        if state.pending == "waiting_short_confirm" and close_price <= up:
            state.position = "short"
            state.pending = None
            state.entry_price = close_price
            state.breakout_up = False  # 重置突破状态
            return "close_long_open_short"

    return None