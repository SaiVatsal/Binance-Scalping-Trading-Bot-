"""
Centralized configuration for the Binance Scalping Bot.
All tunable parameters live here. Override via environment variables.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────
# Exchange
# ──────────────────────────────────────────────
API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")
USE_TESTNET = os.getenv("USE_TESTNET", "true").lower() == "true"

# Binance Futures endpoints
BASE_URL_LIVE = "https://fapi.binance.com"
BASE_URL_TESTNET = "https://testnet.binancefuture.com"
WS_URL_LIVE = "wss://fstream.binance.com"
WS_URL_TESTNET = "wss://stream.binancefuture.com"

BASE_URL = BASE_URL_TESTNET if USE_TESTNET else BASE_URL_LIVE
WS_URL = WS_URL_TESTNET if USE_TESTNET else WS_URL_LIVE

# ──────────────────────────────────────────────
# Trading Pairs & Timeframe
# ──────────────────────────────────────────────
PAIRS = ["XAUUSDT", "BTCUSDT", "ETHUSDT"]
TIMEFRAME = "1m"
KLINE_LIMIT = 250  # Rolling candle window

# ──────────────────────────────────────────────
# Indicator Parameters
# ──────────────────────────────────────────────
EMA_FAST = 9
EMA_SLOW = 21
EMA_TREND = 200
RSI_PERIOD = 7
VWAP_PERIOD = 20  # Session-based reset
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
VOLUME_SPIKE_PERIOD = 20
VOLUME_SPIKE_MULTIPLIER = 1.5

# ──────────────────────────────────────────────
# Strategy
# ──────────────────────────────────────────────
USE_MACD_FILTER = False  # Optional MACD confirmation
ATR_PERIOD = 14
ATR_MIN_THRESHOLD = 0.0003  # Minimum ATR as % of price (skip low vol)
SR_LOOKBACK = 20  # Bars for support/resistance detection
SR_PROXIMITY_PCT = 0.0  # Disabled — blocks too many trending trades
TRADE_COOLDOWN_BARS = 10  # Minimum bars between trades on same pair
EMA_SPREAD_MIN = 0.0003  # Min % spread between EMA9 and EMA21 for alignment

# ──────────────────────────────────────────────
# Take Profit / Stop Loss (as decimal %)
# ──────────────────────────────────────────────
TP_MIN = 0.005  # 0.5%
TP_MAX = 0.012  # 1.2%
TP_DEFAULT = 0.008  # 0.8%
SL_MIN = 0.002  # 0.2%
SL_MAX = 0.004  # 0.4%
SL_DEFAULT = 0.003  # 0.3%
TRAIL_ACTIVATE = 0.003  # Activate trailing at +0.3%
TRAIL_DISTANCE = 0.002  # Trail distance = 0.2%

# ──────────────────────────────────────────────
# Risk Management
# ──────────────────────────────────────────────
RISK_PER_TRADE = 0.0075  # 0.75% of equity
MAX_CONCURRENT_TRADES = 3
AUTO_LEVERAGE = True  # Fetch max leverage from exchange
DEFAULT_LEVERAGE = 20  # Fallback if auto-fetch fails
MAX_CONSECUTIVE_LOSSES = 3
MAX_DAILY_DRAWDOWN = 0.02  # 2%
REDUCE_SIZE_AFTER_LOSSES = 2  # Halve size after N consecutive losses

# ──────────────────────────────────────────────
# Execution
# ──────────────────────────────────────────────
MAX_SPREAD_PCT = 0.0005  # 0.05% max spread for entry
FEE_RATE = 0.0004  # 0.04% per side (Binance Futures taker)
FEE_BNB_DISCOUNT = 0.00075  # 0.075% with BNB
USE_BNB_FEES = False
SLIPPAGE_PCT = 0.0001  # 0.01% simulated slippage (backtest)
ORDER_RETRY_ATTEMPTS = 3
ORDER_RETRY_DELAY = 0.5  # Seconds between retries

# ──────────────────────────────────────────────
# Logging & Output
# ──────────────────────────────────────────────
LOG_DIR = "logs"
RESULTS_DIR = "results"
TRADE_JOURNAL_FILE = "trade_journal.csv"
LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
LOG_BACKUP_COUNT = 5

# ──────────────────────────────────────────────
# Backtest
# ──────────────────────────────────────────────
BACKTEST_CACHE_DIR = "data_cache"
INITIAL_CAPITAL = 10000.0  # USDT
