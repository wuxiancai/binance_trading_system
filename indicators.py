import pandas as pd

class Indicator:
    def __init__(self, window: int = 20, boll_multiplier: float = 2.0, boll_ddof: int = 0, max_rows: int = 200):
        self.window = window
        self.boll_multiplier = boll_multiplier
        self.boll_ddof = boll_ddof
        self.max_rows = max_rows
        self.df = pd.DataFrame(columns=["open_time","close_time","open","high","low","close","volume","is_closed"]).astype({
            "open_time":"int64","close_time":"int64","open":"float64","high":"float64","low":"float64","close":"float64","volume":"float64","is_closed":"bool"
        })

    def add_kline(self, k) -> tuple[float|None, float|None, float|None, float|None]:
        row = {
            "open_time": k.open_time,
            "close_time": k.close_time,
            "open": k.open,
            "high": k.high,
            "low": k.low,
            "close": k.close,
            "volume": k.volume,
            "is_closed": k.is_closed,
        }
        self.df.loc[len(self.df)] = row
        # keep last N rows to bound memory
        if len(self.df) > self.max_rows:
            self.df = self.df.iloc[-self.max_rows:].reset_index(drop=True)
        # 使用已收盘的K线来计算BOLL，保证与交易所一致
        closed_df = self.df[self.df["is_closed"] == True]
        if len(closed_df) < self.window:
            return None, None, None, None
        closes = closed_df["close"].tail(self.window)
        ma = closes.mean()
        std = closes.std(ddof=self.boll_ddof)
        up = ma + self.boll_multiplier * std
        dn = ma - self.boll_multiplier * std
        return ma, std, up, dn

    # === New: compute realtime BOLL using last window-1 closed closes + current forming close ===
    def compute_realtime_boll(self, current_close: float) -> tuple[float|None, float|None, float|None, float|None]:
        """
        返回基于“最近 window-1 根已收盘K线 + 当前形成中的最新价(current_close)”计算的实时BOLL。
        当已收盘K线数量不足 window-1 时返回 (None, None, None, None)。
        """
        closed_df = self.df[self.df["is_closed"] == True]
        if len(closed_df) < max(0, self.window - 1):
            return None, None, None, None
        closes = list(closed_df["close"].tail(max(0, self.window - 1)).astype(float)) + [float(current_close)]
        s = pd.Series(closes, dtype="float64")
        ma = s.mean()
        std = s.std(ddof=self.boll_ddof)
        up = ma + self.boll_multiplier * std
        dn = ma - self.boll_multiplier * std
        return float(ma), float(std), float(up), float(dn)