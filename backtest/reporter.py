"""
Backtest performance reporter.
Prints metrics table and generates equity curve chart.
"""

import os

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

from config import settings
from utils.performance import PerformanceTracker
from utils.logger import get_logger

log = get_logger("reporter")


def print_report(metrics: dict):
    """Print formatted performance report to console."""
    print("\n" + "=" * 60)
    print("  BACKTEST PERFORMANCE REPORT")
    print("=" * 60)

    if "error" in metrics:
        print(f"  ERROR: {metrics['error']}")
        return

    rows = [
        ("Total Trades", metrics.get("total_trades", 0)),
        ("Wins", metrics.get("wins", 0)),
        ("Losses", metrics.get("losses", 0)),
        ("Win Rate", metrics.get("win_rate", "N/A")),
        ("", ""),
        ("Avg Win", f"${metrics.get('avg_win', 0)} USDT"),
        ("Avg Loss", f"${metrics.get('avg_loss', 0)} USDT"),
        ("Win/Loss Ratio", metrics.get("win_loss_ratio", "N/A")),
        ("", ""),
        ("Profit Factor", metrics.get("profit_factor", "N/A")),
        ("Total PnL", f"${metrics.get('total_pnl', 0)} USDT"),
        ("Expectancy/Trade", f"${metrics.get('expectancy_per_trade', 0)} USDT"),
        ("", ""),
        ("Max Drawdown", metrics.get("max_drawdown", "N/A")),
        ("Max Consec. Losses", metrics.get("max_consecutive_losses", 0)),
        ("Sharpe Ratio", metrics.get("sharpe_ratio", "N/A")),
        ("", ""),
        ("Starting Equity", f"${metrics.get('starting_equity', 0)}"),
        ("Final Equity", f"${metrics.get('final_equity', 0)}"),
        ("Return", metrics.get("return_pct", "N/A")),
    ]

    for label, value in rows:
        if label == "":
            print("  " + "-" * 40)
        else:
            print(f"  {label:<25} {value}")

    print("=" * 60 + "\n")


def plot_equity_curve(tracker: PerformanceTracker, pair: str = "",
                       save_path: str = None):
    """Generate and save equity curve chart."""
    if not tracker.equity_curve:
        log.warning("No equity data to plot")
        return

    os.makedirs(settings.RESULTS_DIR, exist_ok=True)

    df = pd.DataFrame(tracker.equity_curve)
    df["ts"] = pd.to_datetime(df["ts"])

    fig, axes = plt.subplots(2, 1, figsize=(14, 8), height_ratios=[3, 1],
                              gridspec_kw={"hspace": 0.3})

    # ── Equity Curve ──
    ax1 = axes[0]
    ax1.fill_between(df["ts"], df["equity"], alpha=0.15, color="#00bcd4")
    ax1.plot(df["ts"], df["equity"], color="#00bcd4", linewidth=1.5, label="Equity")
    ax1.axhline(tracker.starting_equity, color="#666", linestyle="--",
                linewidth=0.8, label=f"Start: ${tracker.starting_equity:,.0f}")
    ax1.set_title(f"Equity Curve — {pair}" if pair else "Equity Curve",
                   fontsize=14, fontweight="bold")
    ax1.set_ylabel("Equity (USDT)")
    ax1.legend(loc="upper left")
    ax1.grid(True, alpha=0.3)
    ax1.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"${x:,.0f}"))

    # ── Per-trade P&L bars ──
    ax2 = axes[1]
    colors = ["#4caf50" if p > 0 else "#f44336" for p in df["trade_pnl"]]
    ax2.bar(range(len(df)), df["trade_pnl"], color=colors, width=1.0, alpha=0.7)
    ax2.axhline(0, color="#666", linewidth=0.5)
    ax2.set_title("Per-Trade P&L", fontsize=12)
    ax2.set_ylabel("USDT")
    ax2.set_xlabel("Trade #")
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()

    save_path = save_path or os.path.join(settings.RESULTS_DIR, f"equity_{pair}.png")
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close()
    log.info(f"Equity curve saved to {save_path}")


def plot_drawdown_curve(tracker: PerformanceTracker, pair: str = "",
                         save_path: str = None):
    """Generate drawdown visualization."""
    if not tracker.equity_curve:
        return

    os.makedirs(settings.RESULTS_DIR, exist_ok=True)

    df = pd.DataFrame(tracker.equity_curve)
    df["ts"] = pd.to_datetime(df["ts"])

    # Compute running drawdown
    peak = df["equity"].cummax()
    drawdown = (peak - df["equity"]) / peak * 100

    fig, ax = plt.subplots(figsize=(14, 4))
    ax.fill_between(df["ts"], drawdown, alpha=0.3, color="#f44336")
    ax.plot(df["ts"], drawdown, color="#f44336", linewidth=1)
    ax.set_title(f"Drawdown — {pair}" if pair else "Drawdown",
                  fontsize=14, fontweight="bold")
    ax.set_ylabel("Drawdown (%)")
    ax.set_xlabel("Time")
    ax.grid(True, alpha=0.3)
    ax.invert_yaxis()

    save_path = save_path or os.path.join(settings.RESULTS_DIR, f"drawdown_{pair}.png")
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close()
    log.info(f"Drawdown chart saved to {save_path}")
