"""
Trade journal and real-time performance tracking.
"""

import os
import csv
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

from config import settings
from utils.logger import get_logger

log = get_logger("performance")


@dataclass
class TradeRecord:
    """Single completed trade record."""
    timestamp: str
    pair: str
    side: str  # LONG or SHORT
    entry_price: float
    exit_price: float
    quantity: float
    pnl_usdt: float
    pnl_pct: float
    fees: float
    duration_seconds: float
    exit_reason: str  # TP, SL, TRAIL, SIGNAL

    @property
    def net_pnl(self) -> float:
        return self.pnl_usdt - self.fees


@dataclass
class PerformanceTracker:
    """Tracks all trades and computes running metrics."""

    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)
    starting_equity: float = settings.INITIAL_CAPITAL
    current_equity: float = settings.INITIAL_CAPITAL
    peak_equity: float = settings.INITIAL_CAPITAL
    daily_start_equity: float = settings.INITIAL_CAPITAL

    # Counters
    total_wins: int = 0
    total_losses: int = 0
    consecutive_losses: int = 0
    consecutive_wins: int = 0
    max_consecutive_losses: int = 0

    # Daily
    daily_pnl: float = 0.0
    daily_trades: int = 0

    def record_trade(self, trade: TradeRecord):
        """Record a completed trade and update metrics."""
        self.trades.append(trade)
        net = trade.net_pnl
        self.current_equity += net
        self.daily_pnl += net
        self.daily_trades += 1

        self.equity_curve.append({
            "ts": trade.timestamp,
            "equity": self.current_equity,
            "trade_pnl": net,
        })

        if net > 0:
            self.total_wins += 1
            self.consecutive_losses = 0
            self.consecutive_wins += 1
        else:
            self.total_losses += 1
            self.consecutive_wins = 0
            self.consecutive_losses += 1
            self.max_consecutive_losses = max(
                self.max_consecutive_losses, self.consecutive_losses
            )

        if self.current_equity > self.peak_equity:
            self.peak_equity = self.current_equity

        self._write_trade_to_csv(trade)
        log.trade(
            f"{trade.pair} {trade.side} | PnL: {net:+.4f} USDT | Equity: {self.current_equity:.2f}",
        )

    def reset_daily(self):
        """Reset daily counters (call at session start)."""
        self.daily_start_equity = self.current_equity
        self.daily_pnl = 0.0
        self.daily_trades = 0

    @property
    def daily_drawdown_pct(self) -> float:
        if self.daily_start_equity == 0:
            return 0.0
        return (self.daily_start_equity - self.current_equity) / self.daily_start_equity

    @property
    def max_drawdown_pct(self) -> float:
        if self.peak_equity == 0:
            return 0.0
        return (self.peak_equity - self.current_equity) / self.peak_equity

    @property
    def win_rate(self) -> float:
        total = self.total_wins + self.total_losses
        return self.total_wins / total if total > 0 else 0.0

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    def compute_metrics(self) -> dict:
        """Compute full performance report."""
        if not self.trades:
            return {"error": "No trades recorded"}

        wins = [t for t in self.trades if t.net_pnl > 0]
        losses = [t for t in self.trades if t.net_pnl <= 0]

        avg_win = sum(t.net_pnl for t in wins) / len(wins) if wins else 0
        avg_loss = abs(sum(t.net_pnl for t in losses) / len(losses)) if losses else 0
        gross_profit = sum(t.net_pnl for t in wins)
        gross_loss = abs(sum(t.net_pnl for t in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        total_pnl = sum(t.net_pnl for t in self.trades)
        expectancy = total_pnl / len(self.trades)

        # Sharpe ratio (per-trade returns)
        returns = [t.pnl_pct for t in self.trades]
        if len(returns) > 1:
            import numpy as np
            ret_arr = np.array(returns)
            sharpe = (ret_arr.mean() / ret_arr.std()) * (252 ** 0.5) if ret_arr.std() > 0 else 0
        else:
            sharpe = 0

        # Max drawdown from equity curve
        max_dd = self._compute_max_drawdown()

        return {
            "total_trades": len(self.trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": f"{self.win_rate:.2%}",
            "avg_win": f"{avg_win:.4f}",
            "avg_loss": f"{avg_loss:.4f}",
            "win_loss_ratio": f"{avg_win / avg_loss:.2f}" if avg_loss > 0 else "inf",
            "profit_factor": f"{profit_factor:.2f}",
            "total_pnl": f"{total_pnl:.4f}",
            "expectancy_per_trade": f"{expectancy:.4f}",
            "max_drawdown": f"{max_dd:.2%}",
            "max_consecutive_losses": self.max_consecutive_losses,
            "sharpe_ratio": f"{sharpe:.2f}",
            "starting_equity": f"{self.starting_equity:.2f}",
            "final_equity": f"{self.current_equity:.2f}",
            "return_pct": f"{(self.current_equity - self.starting_equity) / self.starting_equity:.2%}",
        }

    def _compute_max_drawdown(self) -> float:
        """Walk equity curve to find maximum peak-to-trough drawdown."""
        if not self.equity_curve:
            return 0.0

        peak = self.equity_curve[0]["equity"]
        max_dd = 0.0
        for point in self.equity_curve:
            eq = point["equity"]
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
        return max_dd

    def _write_trade_to_csv(self, trade: TradeRecord):
        """Append trade to CSV journal."""
        os.makedirs(settings.RESULTS_DIR, exist_ok=True)
        path = os.path.join(settings.RESULTS_DIR, settings.TRADE_JOURNAL_FILE)
        file_exists = os.path.exists(path)

        with open(path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(asdict(trade).keys()) + ["net_pnl"])
            if not file_exists:
                writer.writeheader()
            row = asdict(trade)
            row["net_pnl"] = trade.net_pnl
            writer.writerow(row)
