"""
Async REST client for Binance USDT-M Futures.
HMAC-SHA256 signed requests, rate-limit aware.
"""

import time
import hashlib
import hmac
from urllib.parse import urlencode
from typing import Optional

import aiohttp

from config import settings
from utils.logger import get_logger

log = get_logger("rest_client")


class BinanceRestClient:
    """Async Binance Futures REST API wrapper."""

    def __init__(self, api_key: str = None, api_secret: str = None,
                 testnet: bool = None):
        self.api_key = api_key or settings.API_KEY
        self.api_secret = api_secret or settings.API_SECRET
        self.testnet = testnet if testnet is not None else settings.USE_TESTNET
        self.base_url = settings.BASE_URL_TESTNET if self.testnet else settings.BASE_URL_LIVE
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=False)
            self._session = aiohttp.ClientSession(
                headers={"X-MBX-APIKEY": self.api_key},
                connector=connector,
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    def _sign(self, params: dict) -> dict:
        """Add timestamp and HMAC signature to params."""
        params["timestamp"] = int(time.time() * 1000)
        query = urlencode(params)
        signature = hmac.new(
            self.api_secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        params["signature"] = signature
        return params

    async def _request(self, method: str, endpoint: str, params: dict = None,
                        signed: bool = False) -> dict:
        """Execute HTTP request."""
        session = await self._get_session()
        url = f"{self.base_url}{endpoint}"
        params = params or {}

        if signed:
            params = self._sign(params)

        try:
            if method == "GET":
                async with session.get(url, params=params) as resp:
                    data = await resp.json()
            elif method == "POST":
                async with session.post(url, params=params) as resp:
                    data = await resp.json()
            elif method == "DELETE":
                async with session.delete(url, params=params) as resp:
                    data = await resp.json()
            else:
                raise ValueError(f"Unsupported method: {method}")

            if isinstance(data, dict) and "code" in data and data["code"] != 200:
                log.error(f"API error: {data}")
                raise Exception(f"Binance API error: {data.get('msg', data)}")

            return data

        except aiohttp.ClientError as e:
            log.error(f"HTTP error on {endpoint}: {e}")
            raise

    # ── Public endpoints ──

    async def get_exchange_info(self) -> dict:
        return await self._request("GET", "/fapi/v1/exchangeInfo")

    async def get_ticker(self, symbol: str) -> dict:
        return await self._request("GET", "/fapi/v1/ticker/price",
                                    {"symbol": symbol})

    async def get_order_book(self, symbol: str, limit: int = 5) -> dict:
        return await self._request("GET", "/fapi/v1/depth",
                                    {"symbol": symbol, "limit": limit})

    async def get_klines(self, symbol: str, interval: str = "1m",
                          limit: int = 250, start_time: int = None,
                          end_time: int = None) -> list:
        """Fetch historical klines."""
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        return await self._request("GET", "/fapi/v1/klines", params)

    # ── Private (signed) endpoints ──

    async def get_balance(self) -> list:
        return await self._request("GET", "/fapi/v2/balance", signed=True)

    async def get_account(self) -> dict:
        return await self._request("GET", "/fapi/v2/account", signed=True)

    async def get_position_risk(self, symbol: str = None) -> list:
        params = {}
        if symbol:
            params["symbol"] = symbol
        return await self._request("GET", "/fapi/v2/positionRisk",
                                    params, signed=True)

    async def place_order(self, symbol: str, side: str, order_type: str,
                           quantity: float, price: float = None,
                           stop_price: float = None,
                           reduce_only: bool = False) -> dict:
        """Place a futures order.
        
        Args:
            symbol: Trading pair
            side: BUY or SELL
            order_type: MARKET, LIMIT, STOP_MARKET, TAKE_PROFIT_MARKET
            quantity: Order quantity
            price: Limit price (for LIMIT orders)
            stop_price: Trigger price (for STOP/TP orders)
            reduce_only: Close-only order
        """
        params = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "quantity": f"{quantity:.6f}",
        }

        if price:
            params["price"] = f"{price:.2f}"
            params["timeInForce"] = "GTC"

        if stop_price:
            params["stopPrice"] = f"{stop_price:.2f}"

        if reduce_only:
            params["reduceOnly"] = "true"

        log.info(f"Placing order: {side} {order_type} {quantity:.6f} {symbol}")
        return await self._request("POST", "/fapi/v1/order", params, signed=True)

    async def cancel_order(self, symbol: str, order_id: int) -> dict:
        return await self._request("DELETE", "/fapi/v1/order",
                                    {"symbol": symbol, "orderId": order_id},
                                    signed=True)

    async def cancel_all_orders(self, symbol: str) -> dict:
        return await self._request("DELETE", "/fapi/v1/allOpenOrders",
                                    {"symbol": symbol}, signed=True)

    async def get_open_orders(self, symbol: str = None) -> list:
        params = {}
        if symbol:
            params["symbol"] = symbol
        return await self._request("GET", "/fapi/v1/openOrders",
                                    params, signed=True)

    async def set_leverage(self, symbol: str, leverage: int) -> dict:
        return await self._request("POST", "/fapi/v1/leverage",
                                    {"symbol": symbol, "leverage": leverage},
                                    signed=True)

    async def get_leverage_brackets(self, symbol: str = None) -> list:
        """Fetch leverage brackets (max leverage per notional tier)."""
        params = {}
        if symbol:
            params["symbol"] = symbol
        return await self._request("GET", "/fapi/v1/leverageBracket",
                                    params, signed=True)
