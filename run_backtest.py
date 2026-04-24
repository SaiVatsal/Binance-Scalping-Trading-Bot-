"""
Backtest runner — CLI entry point.
Fetches historical data, runs strategy simulation, prints report + charts.
"""

import asyncio
import argparse
import sys

from config import settings
from backtest.data_loader import fetch_klines
from backtest.engine import BacktestEngine
from backtest.reporter import print_report, plot_equity_curve, plot_drawdown_curve
from utils.logger import get_logger

log = get_logger("run_backtest")


async def run(pair: str, start: str, end: str, capital: float):
    """Execute backtest pipeline."""
    log.info(f"{'=' * 50}")
    log.info(f"  BACKTEST: {pair}")
    log.info(f"  Period: {start} → {end}")
    log.info(f"  Capital: ${capital:,.2f}")
    log.info(f"{'=' * 50}")

    # 1. Fetch data
    log.info("Fetching historical data...")
    df = await fetch_klines(pair, settings.TIMEFRAME, start, end)

    if df.empty:
        log.error("No data returned. Check dates and pair.")
        return

    log.info(f"Loaded {len(df)} candles")

    # 2. Run backtest
    engine = BacktestEngine(initial_capital=capital)
    metrics = engine.run(pair, df)

    # 3. Print report
    print_report(metrics)

    # 4. Generate charts
    plot_equity_curve(engine.tracker, pair=pair)
    plot_drawdown_curve(engine.tracker, pair=pair)

    log.info(f"Results saved to {settings.RESULTS_DIR}/")


def main():
    parser = argparse.ArgumentParser(description="Backtest Scalping Strategy")
    parser.add_argument("--pair", type=str, default="BTCUSDT",
                        help="Trading pair (default: BTCUSDT)")
    parser.add_argument("--start", type=str, default="2025-01-01",
                        help="Start date YYYY-MM-DD")
    parser.add_argument("--end", type=str, default="2025-07-01",
                        help="End date YYYY-MM-DD")
    parser.add_argument("--capital", type=float, default=settings.INITIAL_CAPITAL,
                        help=f"Starting capital (default: {settings.INITIAL_CAPITAL})")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(run(args.pair, args.start, args.end, args.capital))


if __name__ == "__main__":
    main()
