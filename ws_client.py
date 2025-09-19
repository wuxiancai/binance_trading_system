import asyncio
import json
import logging
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
    def __init__(
        self,
        ws_base: str,
        symbol: str,
        interval: str,
        ping_interval: int = 20,
        ping_timeout: int = 60,
        backoff_initial: int = 1,
        backoff_max: int = 60,
        open_timeout: int = 20,
    ):
        self.ws_base = ws_base.rstrip("/")
        self.symbol = symbol.lower()
        self.interval = interval
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout
        self.backoff_initial = backoff_initial
        self.backoff_max = backoff_max
        self.open_timeout = open_timeout
        self._stop = asyncio.Event()

    @property
    def stream_url(self) -> str:
        return f"{self.ws_base}/ws/{self.symbol}@kline_{self.interval}"

    async def connect_and_listen(self, on_kline):
        backoff = self.backoff_initial
        while not self._stop.is_set():
            try:
                # 构造多主机、多路径候选以提升不同网络环境下的连通性
                host_candidates = []
                for h in [
                    self.ws_base,
                    "wss://fstream.binance.com",
                    "wss://stream.binancefuture.com",
                ]:
                    if h and h not in host_candidates:
                        host_candidates.append(h.rstrip("/"))

                candidates = []
                for base in host_candidates:
                    candidates.append(f"{base}/ws/{self.symbol}@kline_{self.interval}")
                    candidates.append(
                        f"{base}/stream?streams={self.symbol}@kline_{self.interval}"
                    )

                connected = False
                last_error_tb = None
                last_error_msg = None
                for url in candidates:
                    try:
                        async with websockets.connect(
                            url,
                            ping_interval=self.ping_interval,
                            ping_timeout=self.ping_timeout,
                            open_timeout=self.open_timeout,
                        ) as ws:
                            logging.info(f"Connected WS: {url}")
                            backoff = self.backoff_initial
                            connected = True
                            async for msg in ws:
                                try:
                                    data = json.loads(msg)
                                    payload = data.get("data", data)  # support /stream envelope
                                    if "k" in payload:
                                        k = payload["k"]
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
                                    logging.error(
                                        "Failed to process WS message:\n" + traceback.format_exc()
                                    )
                            # If the stream exits normally, break candidate loop and retry outer while
                            break
                    except Exception as e:
                        # Keep last error and traceback for reporting if all candidates fail
                        last_error_tb = traceback.format_exc()
                        last_error_msg = f"{type(e).__name__}: {e}"
                        logging.debug(
                            f"WS connect failed for {url}, will try next candidate\n{last_error_tb}"
                        )

                if not connected:
                    # 简化 WARN 日志，避免每次都输出长栈；完整堆栈在 DEBUG 级别
                    logging.warning(
                        f"WS connect failed for all candidates; retrying in {backoff}s. Last error: {last_error_msg or 'unknown'}"
                    )
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, self.backoff_max)
                    continue
            except asyncio.CancelledError:
                logging.info("WS client task cancelled; shutting down gracefully")
                break
            except Exception:
                logging.warning(
                    "WS connection error, will retry:\n" + traceback.format_exc()
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self.backoff_max)

    async def stop(self):
        self._stop.set()