import aiosqlite
import logging

INIT_SQL = """
CREATE TABLE IF NOT EXISTS klines (
    open_time INTEGER PRIMARY KEY,
    close_time INTEGER NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    is_closed INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS indicators (
    open_time INTEGER PRIMARY KEY,
    ma REAL,
    std REAL,
    up REAL,
    dn REAL
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    signal TEXT NOT NULL,
    price REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    price REAL,
    order_id TEXT,
    status TEXT
);

CREATE TABLE IF NOT EXISTS errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    where_ TEXT NOT NULL,
    error TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS strategy_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    position TEXT NOT NULL,
    pending TEXT,
    entry_price REAL,
    breakout_level REAL,
    breakout_up INTEGER DEFAULT 0,
    breakout_dn INTEGER DEFAULT 0,
    last_close_price REAL
);
"""


class DB:
    def __init__(self, path: str):
        self.path = path

    async def init(self):
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(INIT_SQL)
            await db.commit()
            logging.info("SQLite initialized")

    async def insert_kline(self, k):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO klines(open_time, close_time, open, high, low, close, volume, is_closed) VALUES (?,?,?,?,?,?,?,?)",
                (k.open_time, k.close_time, k.open, k.high, k.low, k.close, k.volume, int(k.is_closed)),
            )
            await db.commit()

    async def upsert_indicator(self, open_time: int, ma: float, std: float, up: float, dn: float):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO indicators(open_time, ma, std, up, dn) VALUES (?,?,?,?,?)",
                (open_time, ma, std, up, dn),
            )
            await db.commit()

    async def log_signal(self, ts: int, signal: str, price: float):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO signals(ts, signal, price) VALUES (?,?,?)",
                (ts, signal, price),
            )
            await db.commit()

    async def log_trade(self, ts: int, side: str, qty: float, price: float | None, order_id: str | None, status: str | None):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO trades(ts, side, qty, price, order_id, status) VALUES (?,?,?,?,?,?)",
                (ts, side, qty, price, order_id, status),
            )
            await db.commit()

    async def log_error(self, ts: int, where_: str, error: str):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO errors(ts, where_, error) VALUES (?,?,?)",
                (ts, where_, error),
            )
            await db.commit()

    async def update_trade_status_on_close(self, close_side: str):
        """当平仓/止损发生时，将最近一条对应方向的开仓记录标记为 OVER。
        不再限定原始 status 必须为 NEW，允许 NEW/FILLED/其他，避免状态不匹配。
        方向映射：
        - 平多/多单止损(SELL_CLOSE/SELL_STOP_LOSS) -> 开多(BUY/BUY_OPEN)
        - 平空/空单止损(BUY_CLOSE/BUY_STOP_LOSS) -> 开空(SELL/SELL_OPEN)
        """
        if close_side in ("SELL_CLOSE", "SELL_STOP_LOSS"):
            open_sides = ("BUY", "BUY_OPEN")
        elif close_side in ("BUY_CLOSE", "BUY_STOP_LOSS"):
            open_sides = ("SELL", "SELL_OPEN")
        else:
            return
        async with aiosqlite.connect(self.path) as db:
            # 使用子查询选取最近一条未标记为OVER的开仓记录
            await db.execute(
                """
                UPDATE trades
                SET status = 'OVER'
                WHERE id = (
                    SELECT id FROM trades
                    WHERE side IN (?, ?)
                      AND (status IS NULL OR status <> 'OVER')
                    ORDER BY ts DESC
                    LIMIT 1
                )
                """,
                open_sides,
            )
            await db.commit()

    async def save_strategy_state(self, ts: int, position: str, pending: str = None, entry_price: float = None, breakout_level: float = None, breakout_up: bool = False, breakout_dn: bool = False, last_close_price: float = None):
        """保存策略状态"""
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO strategy_state(ts, position, pending, entry_price, breakout_level, breakout_up, breakout_dn, last_close_price) VALUES (?,?,?,?,?,?,?,?)",
                (ts, position, pending, entry_price, breakout_level, int(breakout_up), int(breakout_dn), last_close_price),
            )
            await db.commit()

    async def load_latest_strategy_state(self):
        """加载最新的策略状态"""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT position, pending, entry_price, breakout_level, breakout_up, breakout_dn, last_close_price FROM strategy_state ORDER BY ts DESC LIMIT 1"
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        'position': row['position'],
                        'pending': row['pending'],
                        'entry_price': row['entry_price'],
                        'breakout_level': row['breakout_level'],
                        'breakout_up': bool(row['breakout_up']) if row['breakout_up'] is not None else False,
                        'breakout_dn': bool(row['breakout_dn']) if row['breakout_dn'] is not None else False,
                        'last_close_price': row['last_close_price']
                    }
                return None

    async def get_recent_klines(self, limit: int = 30):
        """获取最近的K线数据，按时间升序返回"""
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT open_time, close_time, open, high, low, close, volume FROM klines ORDER BY open_time DESC LIMIT ?",
                (limit,)
            ) as cursor:
                rows = await cursor.fetchall()
                # 返回升序排列的数据（最老的在前面）
                return list(reversed(rows))