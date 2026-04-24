"""
Technical indicators — pure numpy/pandas, no external TA libraries.
EMA, VWAP, RSI, MACD, ATR, volume spike detection.
"""

import numpy as np
import pandas as pd

from config import settings


def compute_ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def compute_rsi(close: pd.Series, period: int = None) -> pd.Series:
    """Relative Strength Index using Wilder's smoothing."""
    period = period or settings.RSI_PERIOD
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def compute_vwap(high: pd.Series, low: pd.Series, close: pd.Series,
                 volume: pd.Series) -> pd.Series:
    """Rolling VWAP (volume-weighted average price).
    Uses cumulative calculation, reset-friendly for session-based use.
    """
    typical_price = (high + low + close) / 3
    cum_tp_vol = (typical_price * volume).cumsum()
    cum_vol = volume.cumsum()
    vwap = cum_tp_vol / cum_vol.replace(0, np.nan)
    return vwap.fillna(close)


def compute_macd(close: pd.Series, fast: int = None, slow: int = None,
                 signal: int = None) -> tuple:
    """MACD line, signal line, and histogram."""
    fast = fast or settings.MACD_FAST
    slow = slow or settings.MACD_SLOW
    signal = signal or settings.MACD_SIGNAL

    ema_fast = compute_ema(close, fast)
    ema_slow = compute_ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = compute_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_atr(high: pd.Series, low: pd.Series, close: pd.Series,
                period: int = None) -> pd.Series:
    """Average True Range."""
    period = period or settings.ATR_PERIOD
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def detect_volume_spike(volume: pd.Series, period: int = None,
                        multiplier: float = None) -> pd.Series:
    """True if current volume exceeds SMA(volume) * multiplier."""
    period = period or settings.VOLUME_SPIKE_PERIOD
    multiplier = multiplier or settings.VOLUME_SPIKE_MULTIPLIER
    vol_sma = volume.rolling(window=period).mean()
    return volume > (vol_sma * multiplier)


def detect_support_resistance(high: pd.Series, low: pd.Series,
                               lookback: int = None) -> tuple:
    """Recent support and resistance levels."""
    lookback = lookback or settings.SR_LOOKBACK
    resistance = high.rolling(window=lookback).max()
    support = low.rolling(window=lookback).min()
    return support, resistance


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """Attach all indicators to a OHLCV DataFrame.

    Expected columns: open, high, low, close, volume
    Returns DataFrame with indicator columns added.
    """
    df = df.copy()

    # EMAs
    df["ema_fast"] = compute_ema(df["close"], settings.EMA_FAST)
    df["ema_slow"] = compute_ema(df["close"], settings.EMA_SLOW)
    df["ema_trend"] = compute_ema(df["close"], settings.EMA_TREND)

    # VWAP
    df["vwap"] = compute_vwap(df["high"], df["low"], df["close"], df["volume"])

    # RSI
    df["rsi"] = compute_rsi(df["close"], settings.RSI_PERIOD)

    # MACD
    macd_line, signal_line, histogram = compute_macd(df["close"])
    df["macd"] = macd_line
    df["macd_signal"] = signal_line
    df["macd_hist"] = histogram

    # ATR
    df["atr"] = compute_atr(df["high"], df["low"], df["close"])
    df["atr_pct"] = df["atr"] / df["close"]

    # Volume spike
    df["vol_spike"] = detect_volume_spike(df["volume"])

    # Support / Resistance
    df["support"], df["resistance"] = detect_support_resistance(
        df["high"], df["low"]
    )

    # Crossover helpers
    df["ema_fast_prev"] = df["ema_fast"].shift(1)
    df["ema_slow_prev"] = df["ema_slow"].shift(1)
    df["rsi_prev"] = df["rsi"].shift(1)

    # EMA crossovers
    df["ema_cross_up"] = (df["ema_fast"] > df["ema_slow"]) & (
        df["ema_fast_prev"] <= df["ema_slow_prev"]
    )
    df["ema_cross_down"] = (df["ema_fast"] < df["ema_slow"]) & (
        df["ema_fast_prev"] >= df["ema_slow_prev"]
    )

    # RSI crossovers
    df["rsi_cross_40_up"] = (df["rsi"] > 40) & (df["rsi_prev"] <= 40)
    df["rsi_cross_60_down"] = (df["rsi"] < 60) & (df["rsi_prev"] >= 60)

    return df
