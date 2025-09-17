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
        if len(self.df) < self.window + 5:
            return None, None, None, None
        closes = self.df["close"].tail(self.window)
        ma = closes.mean()
        std = closes.std(ddof=self.boll_ddof)
        up = ma + self.boll_multiplier * std
        dn = ma - self.boll_multiplier * std
        return ma, std, up, dn