"""
Async WebSocket feed for Binance Futures kline + depth streams.
Auto-reconnect, rolling candle buffer.
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Callable, Optional

import aiohttp
import pandas as pd

from config import settings
from utils.logger import get_logger

log = get_logger("ws_feed")


class BinanceWebSocket:
    """Manages WebSocket connections to Binance Futures streams."""

    def __init__(self, pairs: list[str] = None, timeframe: str = None,
                 on_candle: Callable = None, on_tick: Callable = None):
        """
        Args:
            pairs: List of trading pairs
            timeframe: Kline interval (e.g. '1m')
            on_candle: Async callback(pair, df) when candle closes
            on_tick: Async callback(pair, price) on every price update
        """
        self.pairs = [p.lower() for p in (pairs or settings.PAIRS)]
        self.timeframe = timeframe or settings.TIMEFRAME
        self.on_candle = on_candle
        self.on_tick = on_tick

        base = settings.WS_URL_TESTNET if settings.USE_TESTNET else settings.WS_URL_LIVE

        # Combined stream URL
        streams = "/".join(
            f"{p}@kline_{self.timeframe}" for p in self.pairs
        )
        self.ws_url = f"{base}/stream?streams={streams}"

        # Rolling candle buffers: pair -> DataFrame
        self.candles: dict[str, pd.DataFrame] = {
            p.upper(): pd.DataFrame(
                columns=["timestamp", "open", "high", "low", "close", "volume"]
            )
            for p in self.pairs
        }

        self._running = False
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None

    async def start(self):
        """Start WebSocket with auto-reconnect."""
        self._running = True
        while self._running:
            try:
                await self._connect()
            except Exception as e:
                log.error(f"WebSocket error: {e}")
                if self._running:
                    log.info("Reconnecting in 5 seconds...")
                    await asyncio.sleep(5)

    async def stop(self):
        """Gracefully stop the WebSocket."""
        self._running = False
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()
        log.info("WebSocket stopped")

    async def _connect(self):
        """Establish WebSocket connection and process messages."""
        connector = aiohttp.TCPConnector(ssl=False)
        self._session = aiohttp.ClientSession(connector=connector)
        log.info(f"Connecting to {self.ws_url[:60]}...")

        async with self._session.ws_connect(
            self.ws_url, heartbeat=20, receive_timeout=300, ssl=False
        ) as ws:
            self._ws = ws
            log.info(f"Connected. Streaming {len(self.pairs)} pairs.")

            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_message(json.loads(msg.data))
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    log.error(f"WS error: {ws.exception()}")
                    break
                elif msg.type in (aiohttp.WSMsgType.CLOSED,
                                  aiohttp.WSMsgType.CLOSING):
                    break

        if self._session and not self._session.closed:
            await self._session.close()

    async def _handle_message(self, data: dict):
        """Process incoming kline message."""
        if "data" not in data:
            log.debug(f"Non-data message: {list(data.keys())}")
            return

        payload = data["data"]
        if payload.get("e") != "kline":
            return

        k = payload["k"]
        pair = payload["s"]  # e.g. "BTCUSDT"
        is_closed = k["x"]

        candle = {
            "timestamp": pd.Timestamp(k["t"], unit="ms", tz="UTC"),
            "open": float(k["o"]),
            "high": float(k["h"]),
            "low": float(k["l"]),
            "close": float(k["c"]),
            "volume": float(k["v"]),
        }

        if is_closed:
            # Append closed candle and trim buffer
            new_row = pd.DataFrame([candle])
            self.candles[pair] = pd.concat(
                [self.candles[pair], new_row], ignore_index=True
            )

            # Keep rolling window
            if len(self.candles[pair]) > settings.KLINE_LIMIT:
                self.candles[pair] = self.candles[pair].iloc[
                    -settings.KLINE_LIMIT:
                ].reset_index(drop=True)

            # Fire callback
            if self.on_candle and len(self.candles[pair]) >= settings.EMA_TREND + 5:
                await self.on_candle(pair, self.candles[pair].copy())
        else:
            # Update in-progress candle (last row)
            if len(self.candles[pair]) > 0:
                idx = self.candles[pair].index[-1]
                for key, val in candle.items():
                    self.candles[pair].at[idx, key] = val

        # Fire tick callback on every message
        if self.on_tick:
            await self.on_tick(pair, candle["close"])

    def get_candles(self, pair: str) -> pd.DataFrame:
        """Get current candle buffer for a pair."""
        return self.candles.get(pair, pd.DataFrame()).copy()

    async def load_initial_candles(self, rest_client):
        """Pre-fill candle buffer with historical klines via REST."""
        for pair in [p.upper() for p in self.pairs]:
            try:
                raw = await rest_client.get_klines(
                    symbol=pair,
                    interval=self.timeframe,
                    limit=settings.KLINE_LIMIT,
                )
                rows = []
                for k in raw:
                    rows.append({
                        "timestamp": pd.Timestamp(k[0], unit="ms", tz="UTC"),
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4]),
                        "volume": float(k[5]),
                    })
                self.candles[pair] = pd.DataFrame(rows)
                log.info(f"Loaded {len(rows)} historical candles for {pair}")
            except Exception as e:
                log.error(f"Failed to load candles for {pair}: {e}")
