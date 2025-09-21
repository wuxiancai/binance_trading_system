from dataclasses import dataclass

@dataclass
class StrategyState:
    position: str = "flat"  # flat | long | short
    pending: str | None = None  # waiting_short_entry | waiting_long_entry | waiting_short_confirm | waiting_long_confirm
    entry_price: float | None = None  # 开仓价格，用于止损计算（此实现不再使用百分比止损）
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
    实时BOLL策略（符合用户描述）：
    - 启动时 flat。
    - 价格 > 实时BOLL UP：标记 突破UP=YES，pending=waiting_short_entry；当价格再次 < 实时BOLL UP，立即开空。
    - 空仓持有时：若价格 > 实时BOLL UP，立即止损平仓；若价格 < 实时BOLL DN，标记 跌破DN=YES，pending=waiting_long_confirm；当价格再次 > 实时BOLL DN，立即平空并同时开多。
    - 价格 < 实时BOLL DN：标记 突破DN=YES，pending=waiting_long_entry；当价格再次 > 实时BOLL DN，立即开多。
    - 多仓持有时：若价格 < 实时BOLL DN，立即止损平仓；若价格 > 实时BOLL UP，pending=waiting_short_confirm；当价格再次 < 实时BOLL UP，立即平多并开空。

    注：此逻辑对入场/出场/止损均“即时生效”，不依赖K线收盘；only_on_close 参数对这些动作不再生效，仅保留以兼容旧代码。
    """
    # 保护：BOLL 不可用时不动作
    if up is None or dn is None:
        return None

    # 使用当前价格与实时BOLL判断突破标志（影线与当前价任一满足即可）
    broke_up = (close_price > up) or (high_price is not None and high_price > up)
    broke_dn = (close_price < dn) or (low_price is not None and low_price < dn)

    if broke_up:
        state.breakout_up = True
        state.breakout_dn = False
    if broke_dn:
        state.breakout_dn = True
        state.breakout_up = False

    # —— 止损（立即）：以实时BOLL作为止损线 ——
    if state.position == "short":
        if close_price > up:  # 上穿上轨 -> 空仓止损
            state.position = "flat"
            state.pending = None
            state.entry_price = None
            state.breakout_level = None
            # 不清空突破标志，交由后续逻辑/收盘清理
            return "stop_loss_short"
    elif state.position == "long":
        if close_price < dn:  # 下穿下轨 -> 多仓止损
            state.position = "flat"
            state.pending = None
            state.entry_price = None
            state.breakout_level = None
            return "stop_loss_long"

    # —— 开仓/反手逻辑（即时，不等待收盘）——
    if state.position == "flat":
        # 标记等待开仓
        if state.breakout_up and state.pending != "waiting_short_entry":
            state.pending = "waiting_short_entry"
            state.breakout_level = up
        if state.breakout_dn and state.pending != "waiting_long_entry":
            state.pending = "waiting_long_entry"
            state.breakout_level = dn

        # 满足回调条件 -> 立即开仓（使用“当前实时BOLL阈值”）
        if state.pending == "waiting_short_entry" and (close_price < up):
            state.position = "short"
            state.pending = None
            state.entry_price = close_price
            state.breakout_up = False
            return "open_short"
        if state.pending == "waiting_long_entry" and (close_price > dn):
            state.position = "long"
            state.pending = None
            state.entry_price = close_price
            state.breakout_dn = False
            return "open_long"

    elif state.position == "short":
        # 下破DN后，等待回到DN之上确认反手
        if state.breakout_dn and state.pending != "waiting_long_confirm":
            state.pending = "waiting_long_confirm"
            state.breakout_level = dn
        if state.pending == "waiting_long_confirm" and (close_price > dn):
            state.position = "long"
            state.pending = None
            state.entry_price = close_price
            state.breakout_dn = False
            return "close_short_open_long"

    elif state.position == "long":
        # 上破UP后，等待回到UP之下确认反手
        if state.breakout_up and state.pending != "waiting_short_confirm":
            state.pending = "waiting_short_confirm"
            state.breakout_level = up
        if state.pending == "waiting_short_confirm" and (close_price < up):
            state.position = "short"
            state.pending = None
            state.entry_price = close_price
            state.breakout_up = False
            return "close_long_open_short"

    # 清空突破标记：仅在收盘且无等待动作且回到轨道内时清空，便于UI在盘中展示突破
    if is_closed and (dn <= close_price <= up) and (state.pending is None):
        state.breakout_up = False
        state.breakout_dn = False

    if is_closed:
        state.last_close_price = close_price
    return None