"""
Live trading bot entry point.
Async event loop: WebSocket → Indicators → Strategy → Risk → Orders.
"""

import asyncio
import math
import os
import signal
import sys
import argparse
from datetime import datetime, timezone

import pandas as pd

from config import settings
from core.indicators import compute_all
from core.strategy import StrategyEngine, Side
from core.risk_manager import RiskManager
from core.order_manager import OrderManager
from exchange.rest_client import BinanceRestClient
from exchange.ws_feed import BinanceWebSocket
from utils.performance import PerformanceTracker, TradeRecord
from utils.logger import get_logger

log = get_logger("main")


class ScalpingBot:
    """Main trading bot orchestrator."""

    def __init__(self, pairs: list[str] = None, testnet: bool = None):
        self.pairs = pairs or settings.PAIRS
        self.testnet = testnet if testnet is not None else settings.USE_TESTNET

        # Core components
        self.tracker = PerformanceTracker()
        self.risk_mgr = RiskManager(self.tracker)
        self.strategy = StrategyEngine()
        self.rest = BinanceRestClient(testnet=self.testnet)
        self.order_mgr = OrderManager(self.rest)
        self.ws = BinanceWebSocket(
            pairs=self.pairs,
            on_candle=self._on_candle,
            on_tick=self._on_tick,
        )
        self._running = False
        self._last_signals = {}  # pair -> "BUY"/"SELL"/None

        # Enable ANSI colors on Windows
        os.system("")

    async def start(self):
        """Initialize and run the bot."""
        log.info("=" * 50)
        log.info(f"  SCALPING BOT STARTING")
        log.info(f"  Pairs: {', '.join(self.pairs)}")
        log.info(f"  Mode: {'TESTNET' if self.testnet else 'LIVE'}")
        log.info(f"  Timeframe: {settings.TIMEFRAME}")
        log.info(f"  Risk/trade: {settings.RISK_PER_TRADE:.2%}")
        log.info("=" * 50)

        self._running = True
        self._symbol_info = {}  # pair -> {step_size, min_qty, min_notional}

        # Fetch exchange info for quantity precision
        try:
            info = await self.rest.get_exchange_info()
            for sym in info.get("symbols", []):
                if sym["symbol"] in self.pairs:
                    filters = {f["filterType"]: f for f in sym.get("filters", [])}
                    step = float(filters.get("LOT_SIZE", {}).get("stepSize", 0.001))
                    min_qty = float(filters.get("LOT_SIZE", {}).get("minQty", 0.001))
                    min_notional = float(filters.get("MIN_NOTIONAL", {}).get("notional", 5))
                    self._symbol_info[sym["symbol"]] = {
                        "step_size": step,
                        "min_qty": min_qty,
                        "min_notional": min_notional,
                    }
                    log.info(f"{sym['symbol']} | step={step} min_qty={min_qty} min_notional={min_notional}")
        except Exception as e:
            log.error(f"Exchange info fetch failed: {e}")

        # Auto-detect and set leverage per pair
        for pair in self.pairs:
            try:
                if settings.AUTO_LEVERAGE:
                    brackets = await self.rest.get_leverage_brackets(pair)
                    # brackets = [{"symbol": "...", "brackets": [{"bracket":1,"initialLeverage":75,...}]}]
                    max_lev = settings.DEFAULT_LEVERAGE
                    for item in brackets:
                        if item.get("symbol") == pair:
                            tier1 = item["brackets"][0] if item.get("brackets") else {}
                            max_lev = tier1.get("initialLeverage", settings.DEFAULT_LEVERAGE)
                            break
                    leverage = min(int(max_lev), settings.DEFAULT_LEVERAGE)
                else:
                    leverage = settings.DEFAULT_LEVERAGE

                await self.rest.set_leverage(pair, leverage)
                log.info(f"Set {pair} leverage to {leverage}x")
            except Exception as e:
                log.error(f"Failed to set leverage for {pair}: {e}")

        # Fetch and log balance
        try:
            balances = await self.rest.get_balance()
            usdt_bal = next(
                (float(b["balance"]) for b in balances if b["asset"] == "USDT"), 0
            )
            log.info(f"USDT Balance: {usdt_bal:.2f}")
        except Exception as e:
            log.error(f"Balance fetch failed: {e}")

        # Pre-fill candle history
        log.info("Loading historical candles...")
        await self.ws.load_initial_candles(self.rest)

        # Start polling loop (REST-based, since WebSocket may be blocked)
        log.info("Starting REST polling loop (1s interval)...")
        await self._poll_loop()

    async def _poll_loop(self):
        """Poll prices and candles via REST API every second."""
        last_candle_fetch = 0

        while self._running:
            try:
                now = asyncio.get_event_loop().time()

                # Fetch live prices for all pairs
                for pair in self.pairs:
                    try:
                        ticker = await self.rest.get_ticker(pair)
                        price = float(ticker["price"])
                        await self._on_tick(pair, price)
                    except Exception as e:
                        log.error(f"Ticker fetch failed for {pair}: {e}")

                # Fetch candles every 10 seconds for strategy evaluation
                if now - last_candle_fetch >= 10:
                    last_candle_fetch = now
                    for pair in self.pairs:
                        try:
                            raw = await self.rest.get_klines(
                                symbol=pair,
                                interval=settings.TIMEFRAME,
                                limit=settings.KLINE_LIMIT,
                            )
                            rows = [{
                                "timestamp": pd.Timestamp(k[0], unit="ms", tz="UTC"),
                                "open": float(k[1]),
                                "high": float(k[2]),
                                "low": float(k[3]),
                                "close": float(k[4]),
                                "volume": float(k[5]),
                            } for k in raw]
                            df = pd.DataFrame(rows)
                            self.ws.candles[pair] = df
                            await self._on_candle(pair, df.copy())
                        except Exception as e:
                            log.error(f"Candle fetch failed for {pair}: {e}")

                await asyncio.sleep(1)

            except Exception as e:
                log.error(f"Poll loop error: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def stop(self):
        """Graceful shutdown."""
        log.info("Shutting down...")
        self._running = False

        # Close all positions
        for pair in list(self.strategy.positions.keys()):
            pos = self.strategy.positions[pair]
            side = "SELL" if pos.side == Side.LONG else "BUY"
            try:
                await self.order_mgr.place_market_order(
                    pair, side, pos.quantity, reduce_only=True
                )
                log.trade(f"Emergency close: {pair}")
            except Exception as e:
                log.error(f"Failed to close {pair}: {e}")

        await self.ws.stop()
        await self.rest.close()
        log.info("Bot stopped.")

    async def _on_tick(self, pair: str, price: float):
        """Called on every price update. Prints colored price line."""
        sig = self._last_signals.get(pair)
        now = datetime.now().strftime("%H:%M:%S")

        # ANSI colors
        GREEN = "\033[92m"
        RED = "\033[91m"
        WHITE = "\033[97m"
        RESET = "\033[0m"

        if sig == "BUY":
            color = GREEN
            tag = "BUY "
        elif sig == "SELL":
            color = RED
            tag = "SELL"
        else:
            color = WHITE
            tag = "    "

        print(f"{color}{now} | {pair:<10} | ${price:<12.2f} | {tag}{RESET}", flush=True)

    async def _on_candle(self, pair: str, df):
        """Called when a candle closes. Core trading logic."""
        if not self._running:
            return

        try:
            # Compute indicators
            df = compute_all(df)
            current_price = df.iloc[-1]["close"]
            timestamp = str(df.iloc[-1]["timestamp"])

            # ── Check exits ──
            exit_reason = self.strategy.check_exit(pair, current_price)
            if exit_reason:
                await self._execute_exit(pair, current_price, exit_reason, timestamp)

            # ── Check entries ──
            if pair not in self.strategy.positions:
                signal = self.strategy.evaluate(pair, df)
                # Update signal state for tick display
                if signal:
                    self._last_signals[pair] = "BUY" if signal.side == Side.LONG else "SELL"
                else:
                    self._last_signals[pair] = None

                if signal:
                    allowed, reason = self.risk_mgr.can_open_trade()
                    if not allowed:
                        log.risk(f"Trade blocked: {reason}")
                        return

                    if self.strategy.open_position_count >= settings.MAX_CONCURRENT_TRADES:
                        return

                    # Get balance
                    try:
                        balances = await self.rest.get_balance()
                        usdt_bal = next(
                            (float(b["balance"]) for b in balances
                             if b["asset"] == "USDT"), 0
                        )
                    except Exception as e:
                        log.error(f"Balance fetch failed: {e}")
                        return

                    qty = self.risk_mgr.calculate_position_size(
                        usdt_bal, signal.entry_price, signal.stop_loss
                    )

                    if qty <= 0:
                        return

                    # Round quantity to exchange precision
                    sym_info = self._symbol_info.get(pair, {})
                    step = sym_info.get("step_size", 0.001)
                    min_qty = sym_info.get("min_qty", 0.001)
                    min_notional = sym_info.get("min_notional", 5)

                    # Floor to step size
                    qty = math.floor(qty / step) * step
                    qty = max(qty, min_qty)

                    # Check min notional
                    if qty * signal.entry_price < min_notional:
                        log.info(f"Order too small: {qty * signal.entry_price:.2f} < {min_notional} USDT")
                        return

                    # Execute entry
                    entry_side = "BUY" if signal.side == Side.LONG else "SELL"
                    result = await self.order_mgr.place_market_order(
                        pair, entry_side, qty
                    )

                    if result:
                        avg_price = float(result.get("avgPrice", signal.entry_price))
                        signal.entry_price = avg_price
                        self.strategy.open_position(pair, signal, qty, timestamp)

                        # Place SL/TP orders
                        sl_side = "SELL" if signal.side == Side.LONG else "BUY"
                        await self.order_mgr.place_stop_order(
                            pair, sl_side, qty, signal.stop_loss
                        )

        except Exception as e:
            log.error(f"Error processing {pair}: {e}", exc_info=True)

    async def _execute_exit(self, pair: str, price: float, reason: str,
                             timestamp: str):
        """Execute position exit."""
        pos = self.strategy.positions.get(pair)
        if not pos:
            return

        # Cancel existing SL/TP orders
        await self.order_mgr.cancel_all_orders(pair)

        # Market close
        exit_side = "SELL" if pos.side == Side.LONG else "BUY"
        result = await self.order_mgr.place_market_order(
            pair, exit_side, pos.quantity, reduce_only=True
        )

        exit_price = float(result.get("avgPrice", price)) if result else price

        # Calculate P&L
        if pos.side == Side.LONG:
            pnl = (exit_price - pos.entry_price) * pos.quantity
        else:
            pnl = (pos.entry_price - exit_price) * pos.quantity

        pnl_pct = pnl / (pos.entry_price * pos.quantity) if pos.entry_price > 0 else 0
        fees = OrderManager.calculate_fees(pos.quantity, pos.entry_price) + \
               OrderManager.calculate_fees(pos.quantity, exit_price)

        trade = TradeRecord(
            timestamp=timestamp,
            pair=pair,
            side=pos.side.value,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            quantity=pos.quantity,
            pnl_usdt=pnl,
            pnl_pct=pnl_pct,
            fees=fees,
            duration_seconds=0,
            exit_reason=reason,
        )

        self.tracker.record_trade(trade)
        self.strategy.close_position(pair)

        log.trade(
            f"EXIT {reason}: {pos.side.value} {pair} | PnL: {pnl:+.4f} USDT"
        )


def main():
    parser = argparse.ArgumentParser(description="Binance Scalping Bot")
    parser.add_argument("--pairs", nargs="+", default=settings.PAIRS,
                        help="Trading pairs (e.g. BTCUSDT ETHUSDT)")
    parser.add_argument("--live", action="store_true",
                        help="Use live API (default: testnet)")
    args = parser.parse_args()

    testnet = not args.live
    bot = ScalpingBot(pairs=args.pairs, testnet=testnet)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Graceful shutdown
    def shutdown_handler(*_):
        log.info("Received shutdown signal")
        loop.create_task(bot.stop())

    if sys.platform != "win32":
        loop.add_signal_handler(signal.SIGINT, shutdown_handler)
        loop.add_signal_handler(signal.SIGTERM, shutdown_handler)

    try:
        loop.run_until_complete(bot.start())
    except KeyboardInterrupt:
        loop.run_until_complete(bot.stop())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
