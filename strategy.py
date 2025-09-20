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
           is_closed: bool = True, only_on_close: bool = True,
           use_breakout_level_for_entry: bool = False,
           reentry_buffer_pct: float = 0.0) -> str | None:
    """
    基于布林带的突破回调策略（默认按K线收盘价确认），扩展支持影线突破；止损规则改为：
    - 空仓（short）：当实时价格 >= 开仓价 * 1.001 时，立即止损平仓；
    - 多仓（long）：当实时价格 <= 开仓价 * 0.999 时，立即止损平仓；
    止损动作与only_on_close无关，始终即时生效。

    新增：
    - use_breakout_level_for_entry: 回到轨内时使用“突破当时的上/下轨”阈值，而不是“当前最新上/下轨”。
    - reentry_buffer_pct: 回到轨内的缓冲阈值（例如 0.001=0.1%），避免“刚好贴线”误触发。
    """
    # 检查关键参数是否为None，避免TypeError
    if up is None or dn is None:
        return None

    # 原有：基于相邻收盘价的突破判定（可能在同一根形成中的K线仍用上一根收盘价作比较）
    if state.last_close_price is not None:
        if state.last_close_price <= up and close_price > up:
            state.breakout_up = True
            state.breakout_dn = False
        elif state.last_close_price >= dn and close_price < dn:
            state.breakout_dn = True
            state.breakout_up = False

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

    def _can_act() -> bool:
        return is_closed or (not only_on_close)

    # 计算回到轨内的有效阈值（根据配置选用突破时的轨或当前轨，并加入缓冲）
    def _short_reentry_threshold() -> float:
        base = state.breakout_level if (use_breakout_level_for_entry and state.breakout_level) else up
        # 价格需回到 base 以下，并考虑 buffer
        return base * (1 - max(0.0, reentry_buffer_pct))

    def _long_reentry_threshold() -> float:
        base = state.breakout_level if (use_breakout_level_for_entry and state.breakout_level) else dn
        # 价格需回到 base 以上，并考虑 buffer
        return base * (1 + max(0.0, reentry_buffer_pct))

    # 先根据突破标记设置/更新 pending，再考虑是否清空突破标记。
    if state.position == "flat":
        # 标记等待开仓
        if state.breakout_up and state.pending != "waiting_short_entry":
            state.pending = "waiting_short_entry"
            state.breakout_level = up
        if state.breakout_dn and state.pending != "waiting_long_entry":
            state.pending = "waiting_long_entry"
            state.breakout_level = dn

        # 满足回调条件 -> 开仓（遵循 only_on_close 配置）
        if state.pending == "waiting_short_entry" and close_price <= _short_reentry_threshold() and _can_act():
            state.position = "short"
            state.pending = None
            state.entry_price = close_price
            state.breakout_up = False
            if is_closed:
                state.last_close_price = close_price
            return "open_short"
        if state.pending == "waiting_long_entry" and close_price >= _long_reentry_threshold() and _can_act():
            state.position = "long"
            state.pending = None
            state.entry_price = close_price
            state.breakout_dn = False
            if is_closed:
                state.last_close_price = close_price
            return "open_long"

    elif state.position == "short":
        if state.breakout_dn and state.pending != "waiting_long_confirm":
            state.pending = "waiting_long_confirm"
            state.breakout_level = dn
        if state.pending == "waiting_long_confirm" and close_price >= _long_reentry_threshold() and _can_act():
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
        if state.pending == "waiting_short_confirm" and close_price <= _short_reentry_threshold() and _can_act():
            state.position = "short"
            state.pending = None
            state.entry_price = close_price
            state.breakout_up = False
            if is_closed:
                state.last_close_price = close_price
            return "close_long_open_short"

    # 将“回到轨道内则清空突破标记”的处理延后：只有在当前没有等待动作时才清空，避免同一次tick内刚设置就被清空
    if (close_price <= up and close_price >= dn) and (state.pending is None):
        state.breakout_up = False
        state.breakout_dn = False

    # 更新上一根“收盘价基准”：仅在K线收盘时更新
    if is_closed:
        state.last_close_price = close_price
    return None