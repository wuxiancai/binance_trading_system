from dataclasses import dataclass

@dataclass
class StrategyState:
    position: str = "flat"  # flat | long | short
    pending: str | None = None  # waiting_long | waiting_short


def decide(price: float, up: float, dn: float, state: StrategyState) -> str | None:
    # Entry conditions
    if price > up and state.position != "short":
        return "open_short"
    if price < dn and state.position != "long":
        return "open_long"

    # Confirmation logic
    if state.pending == "waiting_short" and price <= up:
        return "confirm_short"
    if state.pending == "waiting_long" and price >= dn:
        return "confirm_long"

    # Transition to waiting states
    if price > up and state.position == "long":
        state.pending = "waiting_short"
    elif price < dn and state.position == "short":
        state.pending = "waiting_long"

    return None