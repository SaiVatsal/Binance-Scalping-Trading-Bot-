"""
Event-driven backtesting engine.
Iterates candle-by-candle, applying indicators → strategy → risk → simulated fills.
"""

from datetime import datetime, timezone

import pandas as pd
import numpy as np

from config import settings
from core.indicators import compute_all
from core.strategy import StrategyEngine, Side
from core.risk_manager import RiskManager
from core.order_manager import OrderManager
from utils.performance import PerformanceTracker, TradeRecord
from utils.logger import get_logger

log = get_logger("backtester")


class BacktestEngine:
    """Simulates trading over historical data."""

    def __init__(self, initial_capital: float = None):
        self.initial_capital = initial_capital or settings.INITIAL_CAPITAL
        self.tracker = PerformanceTracker(
            starting_equity=self.initial_capital,
            current_equity=self.initial_capital,
            peak_equity=self.initial_capital,
            daily_start_equity=self.initial_capital,
        )
        self.risk_mgr = RiskManager(self.tracker)
        self.strategy = StrategyEngine()
        self.balance = self.initial_capital

    def run(self, pair: str, df: pd.DataFrame) -> dict:
        """Run backtest on a single pair.
        
        Args:
            pair: Trading pair symbol
            df: Raw OHLCV DataFrame (timestamp, open, high, low, close, volume)
            
        Returns:
            Performance metrics dict
        """
        log.info(f"Starting backtest: {pair} | {len(df)} candles | Capital: ${self.initial_capital:.2f}")

        # Compute all indicators once (vectorized)
        df = compute_all(df)

        # Warmup period — need EMA_TREND + buffer
        warmup = settings.EMA_TREND + 10
        if len(df) < warmup:
            log.error(f"Not enough data. Need {warmup}, got {len(df)}")
            return {"error": "Insufficient data"}

        # Track current day for daily resets
        current_day = None

        # Iterate candle-by-candle after warmup
        for i in range(warmup, len(df)):
            row = df.iloc[i]
            current_price = row["close"]
            timestamp = str(row["timestamp"])

            # ── Daily reset ──
            try:
                ts = pd.Timestamp(timestamp)
                day = ts.date()
                if current_day is not None and day != current_day:
                    self.risk_mgr.reset_daily()
                    self.tracker.consecutive_losses = 0
                current_day = day
            except Exception:
                pass

            # ── Check exits using intra-bar high/low ──
            high = row["high"]
            low = row["low"]
            if pair in self.strategy.positions:
                pos = self.strategy.positions[pair]
                if pos.side == Side.LONG:
                    # Check SL first (worst case), then TP
                    if low <= pos.stop_loss:
                        self._close_trade(pair, pos.stop_loss, "SL", timestamp)
                    elif high >= pos.take_profit:
                        self._close_trade(pair, pos.take_profit, "TP", timestamp)
                    else:
                        # Check trailing stop with current_price
                        exit_reason = self.strategy.check_exit(pair, current_price)
                        if exit_reason:
                            self._close_trade(pair, current_price, exit_reason, timestamp)
                else:  # SHORT
                    if high >= pos.stop_loss:
                        self._close_trade(pair, pos.stop_loss, "SL", timestamp)
                    elif low <= pos.take_profit:
                        self._close_trade(pair, pos.take_profit, "TP", timestamp)
                    else:
                        exit_reason = self.strategy.check_exit(pair, current_price)
                        if exit_reason:
                            self._close_trade(pair, current_price, exit_reason, timestamp)

            # ── Check for new entry ──
            if pair not in self.strategy.positions:
                # Feed strategy a window of data up to current bar
                window = df.iloc[max(0, i - settings.KLINE_LIMIT):i + 1].copy()
                signal = self.strategy.evaluate(pair, window)

                if signal:
                    # Risk check
                    allowed, reason = self.risk_mgr.can_open_trade()
                    if not allowed:
                        continue

                    # Concurrent position check
                    if self.strategy.open_position_count >= settings.MAX_CONCURRENT_TRADES:
                        continue

                    # Position sizing
                    qty = self.risk_mgr.calculate_position_size(
                        self.balance, signal.entry_price, signal.stop_loss
                    )

                    if qty <= 0:
                        continue

                    # Apply slippage to entry
                    slippage = signal.entry_price * settings.SLIPPAGE_PCT
                    if signal.side == Side.LONG:
                        entry = signal.entry_price + slippage
                    else:
                        entry = signal.entry_price - slippage

                    signal.entry_price = entry

                    # Entry fee
                    fee = qty * entry * settings.FEE_RATE
                    self.balance -= fee

                    self.strategy.open_position(pair, signal, qty, timestamp)

        # Close any remaining open positions at last price
        if pair in self.strategy.positions:
            last_price = df.iloc[-1]["close"]
            self._close_trade(pair, last_price, "END", str(df.iloc[-1]["timestamp"]))

        metrics = self.tracker.compute_metrics()
        log.info(f"Backtest complete. {self.tracker.total_trades} trades executed.")
        return metrics

    def _close_trade(self, pair: str, exit_price: float, reason: str,
                      timestamp: str):
        """Close position and record trade."""
        pos = self.strategy.close_position(pair)
        if not pos:
            return

        # Apply slippage to exit
        slippage = exit_price * settings.SLIPPAGE_PCT
        if pos.side == Side.LONG:
            exit_price -= slippage
        else:
            exit_price += slippage

        # Calculate P&L
        if pos.side == Side.LONG:
            pnl = (exit_price - pos.entry_price) * pos.quantity
        else:
            pnl = (pos.entry_price - exit_price) * pos.quantity

        pnl_pct = pnl / (pos.entry_price * pos.quantity) if pos.entry_price > 0 else 0

        # Exit fee
        exit_fee = pos.quantity * exit_price * settings.FEE_RATE
        entry_fee = pos.quantity * pos.entry_price * settings.FEE_RATE
        total_fees = entry_fee + exit_fee

        # Duration
        try:
            t_entry = pd.Timestamp(pos.entry_time)
            t_exit = pd.Timestamp(timestamp)
            duration = (t_exit - t_entry).total_seconds()
        except Exception:
            duration = 0

        trade = TradeRecord(
            timestamp=timestamp,
            pair=pair,
            side=pos.side.value,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            quantity=pos.quantity,
            pnl_usdt=pnl,
            pnl_pct=pnl_pct,
            fees=total_fees,
            duration_seconds=duration,
            exit_reason=reason,
        )

        self.tracker.record_trade(trade)
        self.balance += pnl - exit_fee

        log.trade(
            f"CLOSED {pos.side.value} {pair} | {reason} | "
            f"PnL: {pnl:+.4f} ({pnl_pct:+.4%}) | Balance: {self.balance:.2f}"
        )
