"""
Order manager — async order execution with retry, slippage guard, fee tracking.
"""

import asyncio
from typing import Optional

from config import settings
from utils.logger import get_logger

log = get_logger("orders")


class OrderManager:
    """Handles order execution against the exchange."""

    def __init__(self, rest_client):
        """
        Args:
            rest_client: Instance of exchange.rest_client.BinanceRestClient
        """
        self.client = rest_client

    async def place_market_order(self, pair: str, side: str, quantity: float,
                                  reduce_only: bool = False) -> Optional[dict]:
        """Place a market order with retry logic.
        
        Args:
            pair: Trading pair (e.g. BTCUSDT)
            side: "BUY" or "SELL"
            quantity: Order quantity in base asset
            reduce_only: If True, order only reduces position
            
        Returns:
            Order response dict or None on failure
        """
        for attempt in range(1, settings.ORDER_RETRY_ATTEMPTS + 1):
            try:
                # Check spread before entry
                if not reduce_only:
                    spread_ok = await self._check_spread(pair)
                    if not spread_ok:
                        log.risk(f"Spread too wide for {pair}, skipping order")
                        return None

                result = await self.client.place_order(
                    symbol=pair,
                    side=side,
                    order_type="MARKET",
                    quantity=quantity,
                    reduce_only=reduce_only,
                )

                log.trade(
                    f"ORDER FILLED: {side} {quantity:.6f} {pair} | "
                    f"Avg price: {result.get('avgPrice', 'N/A')}"
                )
                return result

            except Exception as e:
                log.error(f"Order attempt {attempt}/{settings.ORDER_RETRY_ATTEMPTS} failed: {e}")
                if attempt < settings.ORDER_RETRY_ATTEMPTS:
                    await asyncio.sleep(settings.ORDER_RETRY_DELAY * attempt)

        log.error(f"All {settings.ORDER_RETRY_ATTEMPTS} order attempts failed for {pair}")
        return None

    async def place_stop_order(self, pair: str, side: str, quantity: float,
                                stop_price: float) -> Optional[dict]:
        """Place a stop-market order (for SL)."""
        try:
            result = await self.client.place_order(
                symbol=pair,
                side=side,
                order_type="STOP_MARKET",
                quantity=quantity,
                stop_price=stop_price,
                reduce_only=True,
            )
            log.info(f"STOP order placed: {side} {pair} @ {stop_price:.2f}")
            return result
        except Exception as e:
            log.error(f"Stop order failed: {e}")
            return None

    async def place_tp_order(self, pair: str, side: str, quantity: float,
                              tp_price: float) -> Optional[dict]:
        """Place a take-profit market order."""
        try:
            result = await self.client.place_order(
                symbol=pair,
                side=side,
                order_type="TAKE_PROFIT_MARKET",
                quantity=quantity,
                stop_price=tp_price,
                reduce_only=True,
            )
            log.info(f"TP order placed: {side} {pair} @ {tp_price:.2f}")
            return result
        except Exception as e:
            log.error(f"TP order failed: {e}")
            return None

    async def cancel_all_orders(self, pair: str) -> bool:
        """Cancel all open orders for a pair."""
        try:
            await self.client.cancel_all_orders(symbol=pair)
            log.info(f"Cancelled all orders for {pair}")
            return True
        except Exception as e:
            log.error(f"Cancel orders failed: {e}")
            return False

    async def _check_spread(self, pair: str) -> bool:
        """Check if bid-ask spread is within acceptable range."""
        try:
            book = await self.client.get_order_book(symbol=pair, limit=5)
            best_bid = float(book["bids"][0][0])
            best_ask = float(book["asks"][0][0])
            mid = (best_bid + best_ask) / 2
            spread_pct = (best_ask - best_bid) / mid

            if spread_pct > settings.MAX_SPREAD_PCT:
                log.risk(f"{pair} spread {spread_pct:.5%} > max {settings.MAX_SPREAD_PCT:.5%}")
                return False
            return True
        except Exception as e:
            log.error(f"Spread check failed: {e}")
            return True  # Allow trade if check fails

    @staticmethod
    def calculate_fees(quantity: float, price: float) -> float:
        """Calculate trading fees for one side."""
        notional = quantity * price
        rate = settings.FEE_BNB_DISCOUNT if settings.USE_BNB_FEES else settings.FEE_RATE
        return notional * rate
