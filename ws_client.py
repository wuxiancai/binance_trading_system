import asyncio
import json
import logging
import time
import traceback
from dataclasses import dataclass

import websockets


@dataclass
class KlineEvent:
    open_time: int
    close_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool


class WSClient:
    def __init__(self, ws_base: str, symbol: str, interval: str,
                 ping_interval: int = 20, ping_timeout: int = 60,
                 backoff_initial: int = 1, backoff_max: int = 60):
        self.ws_base = ws_base.rstrip("/")
        self.symbol = symbol.lower()
        self.interval = interval
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.backoff_initial = backoff_initial
        self.backoff_max = backoff_max
        self._stop = asyncio.Event()

    @property
    def stream_url(self) -> str:
        return f"{self.ws_base}/ws/{self.symbol}@kline_{self.interval}"

    async def connect_and_listen(self, on_kline):
        backoff = self.backoff_initial
        while not self._stop.is_set():
            try:
                async with websockets.connect(self.stream_url, ping_interval=self.ping_interval, ping_timeout=self.ping_timeout) as ws:
                    logging.info(f"Connected WS: {self.stream_url}")
                    backoff = self.backoff_initial
                    async for msg in ws:
                        try:
                            data = json.loads(msg)
                            if "k" in data:
                                k = data["k"]
                                evt = KlineEvent(
                                    open_time=int(k["t"]),
                                    close_time=int(k["T"]),
                                    open=float(k["o"]),
                                    high=float(k["h"]),
                                    low=float(k["l"]),
                                    close=float(k["c"]),
                                    volume=float(k["v"]),
                                    is_closed=bool(k["x"]),
                                )
                                await on_kline(evt)
                        except Exception:
                            logging.error("Failed to process WS message:\n" + traceback.format_exc())
            except asyncio.CancelledError:
                break
            except Exception:
                logging.warning("WS connection error, will retry:\n" + traceback.format_exc())
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self.backoff_max)

    async def stop(self):
        self._stop.set()