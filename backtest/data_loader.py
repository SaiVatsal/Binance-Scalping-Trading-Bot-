"""
Historical kline data fetcher with local CSV caching.
Auto-paginates Binance API (max 1000 per request).
"""

import os
import ssl
import asyncio
from datetime import datetime, timezone

import pandas as pd
import aiohttp

from config import settings
from utils.logger import get_logger

log = get_logger("data_loader")

# Binance public API (no auth needed for klines)
KLINE_URL = "https://fapi.binance.com/fapi/v1/klines"


async def fetch_klines(symbol: str, interval: str, start_date: str,
                        end_date: str) -> pd.DataFrame:
    """Fetch historical klines from Binance, with caching.
    
    Args:
        symbol: e.g. "BTCUSDT"
        interval: e.g. "1m"
        start_date: "YYYY-MM-DD"
        end_date: "YYYY-MM-DD"
    
    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume
    """
    cache_path = _cache_path(symbol, interval, start_date, end_date)

    if os.path.exists(cache_path):
        log.info(f"Loading cached data: {cache_path}")
        df = pd.read_csv(cache_path, parse_dates=["timestamp"])
        log.info(f"Loaded {len(df)} candles from cache")
        return df

    log.info(f"Fetching {symbol} {interval} from {start_date} to {end_date}")

    start_ms = int(datetime.strptime(start_date, "%Y-%m-%d")
                    .replace(tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int(datetime.strptime(end_date, "%Y-%m-%d")
                  .replace(tzinfo=timezone.utc).timestamp() * 1000)

    all_rows = []

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    connector = aiohttp.TCPConnector(ssl=ssl_ctx)
    async with aiohttp.ClientSession(connector=connector) as session:
        current_start = start_ms

        while current_start < end_ms:
            params = {
                "symbol": symbol,
                "interval": interval,
                "startTime": current_start,
                "endTime": end_ms,
                "limit": 1000,
            }

            async with session.get(KLINE_URL, params=params) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    log.error(f"API error {resp.status}: {text}")
                    break

                data = await resp.json()

            if not data:
                break

            for k in data:
                all_rows.append({
                    "timestamp": pd.Timestamp(k[0], unit="ms", tz="UTC"),
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                })

            # Move start to after last candle
            last_ts = data[-1][0]
            current_start = last_ts + 1

            log.info(f"  Fetched {len(data)} candles, total: {len(all_rows)}")

            # Rate limit respect
            await asyncio.sleep(0.2)

    if not all_rows:
        log.error("No data fetched")
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    df = df.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)

    # Cache to disk
    os.makedirs(settings.BACKTEST_CACHE_DIR, exist_ok=True)
    df.to_csv(cache_path, index=False)
    log.info(f"Cached {len(df)} candles to {cache_path}")

    return df


def _cache_path(symbol: str, interval: str, start: str, end: str) -> str:
    """Generate cache file path."""
    os.makedirs(settings.BACKTEST_CACHE_DIR, exist_ok=True)
    return os.path.join(
        settings.BACKTEST_CACHE_DIR,
        f"{symbol}_{interval}_{start}_{end}.csv"
    )


async def fetch_multi_pair(pairs: list[str], interval: str, start_date: str,
                            end_date: str) -> dict[str, pd.DataFrame]:
    """Fetch klines for multiple pairs concurrently."""
    tasks = {
        pair: fetch_klines(pair, interval, start_date, end_date)
        for pair in pairs
    }
    results = {}
    for pair, coro in tasks.items():
        results[pair] = await coro
    return results
