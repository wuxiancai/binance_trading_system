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


def decide(close_price: float, up: float, dn: float, state: StrategyState,
           high_price: float | None = None, low_price: float | None = None,
           is_closed: bool = True, only_on_close: bool = True) -> str | None:
    """
    基于布林带的突破回调策略（默认按K线收盘价确认），扩展支持影线突破；止损规则改为：
    - 空仓（short）：当实时价格 >= 开仓价 * 1.001 时，立即止损平仓；
    - 多仓（long）：当实时价格 <= 开仓价 * 0.999 时，立即止损平仓；
    止损动作与only_on_close无关，始终即时生效。
    """
    # 检查关键参数是否为None，避免TypeError
    if up is None or dn is None:
        return None

    # 原有：基于相邻收盘价的突破判定
    if state.last_close_price is not None:
        if state.last_close_price <= up and close_price > up:
            state.breakout_up = True
            state.breakout_dn = False
        elif state.last_close_price >= dn and close_price < dn:
            state.breakout_dn = True
            state.breakout_up = False
        elif close_price <= up and close_price >= dn:
            # 回到轨道内时，若无等待动作可重置突破标记
            if state.pending is None:
                state.breakout_up = False
                state.breakout_dn = False

    # 新增：影线突破（同一根K线内高/低触及阈值）用于及时设置 pending
    if high_price is not None and high_price > up:
        state.breakout_up = True
        state.breakout_dn = False
    if low_price is not None and low_price < dn:
        state.breakout_dn = True
        state.breakout_up = False

    # 止损逻辑（即时）：按开仓价±0.1%
    STOP_PCT = 0.001
    if state.position == "short" and state.entry_price is not None:
        if close_price >= state.entry_price * (1 + STOP_PCT):
            state.position = "flat"
            state.pending = None
            state.entry_price = None
            state.breakout_level = None
            state.breakout_up = False
            state.breakout_dn = False
            if is_closed:
                state.last_close_price = close_price
            return "stop_loss_short"
    elif state.position == "long" and state.entry_price is not None:
        if close_price <= state.entry_price * (1 - STOP_PCT):
            state.position = "flat"
            state.pending = None
            state.entry_price = None
            state.breakout_level = None
            state.breakout_up = False
            state.breakout_dn = False
            if is_closed:
                state.last_close_price = close_price
            return "stop_loss_long"

    # 1) 止损（原按上/下轨的逻辑已被上面替代）
    def _can_act() -> bool:
        return is_closed or (not only_on_close)

    # 2) 首次开仓逻辑（flat）
    if state.position == "flat":
        # 标记等待开仓
        if state.breakout_up and state.pending != "waiting_short_entry":
            state.pending = "waiting_short_entry"
            state.breakout_level = up
        if state.breakout_dn and state.pending != "waiting_long_entry":
            state.pending = "waiting_long_entry"
            state.breakout_level = dn

        # 满足回调条件 -> 开仓（遵循 only_on_close 配置）
        if state.pending == "waiting_short_entry" and close_price <= up and _can_act():
            state.position = "short"
            state.pending = None
            state.entry_price = close_price
            state.breakout_up = False
            if is_closed:
                state.last_close_price = close_price
            return "open_short"
        if state.pending == "waiting_long_entry" and close_price >= dn and _can_act():
            state.position = "long"
            state.pending = None
            state.entry_price = close_price
            state.breakout_dn = False
            if is_closed:
                state.last_close_price = close_price
            return "open_long"

    # 3) 持仓后的翻转逻辑
    elif state.position == "short":
        # 跌破下轨后等待反弹确认（影线或收盘均可设置等待）
        if state.breakout_dn and state.pending != "waiting_long_confirm":
            state.pending = "waiting_long_confirm"
            state.breakout_level = dn
        if state.pending == "waiting_long_confirm" and close_price >= dn and _can_act():
            state.position = "long"
            state.pending = None
            state.entry_price = close_price
            state.breakout_dn = False
            if is_closed:
                state.last_close_price = close_price
            return "close_short_open_long"

    elif state.position == "long":
        if state.breakout_up and state.pending != "waiting_short_confirm":
            state.pending = "waiting_short_confirm"
            state.breakout_level = up
        if state.pending == "waiting_short_confirm" and close_price <= up and _can_act():
            state.position = "short"
            state.pending = None
            state.entry_price = close_price
            state.breakout_up = False
            if is_closed:
                state.last_close_price = close_price
            return "close_long_open_short"

    # 更新上一根“收盘价基准”：仅在K线收盘时更新
    if is_closed:
        state.last_close_price = close_price
    return None