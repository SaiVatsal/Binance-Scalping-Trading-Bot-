import aiohttp, asyncio, time, hmac, hashlib
from urllib.parse import urlencode
from dotenv import load_dotenv
import os

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")

print(f"Key length: {len(API_KEY)}")
print(f"Secret length: {len(API_SECRET)}")
print(f"Key starts: {API_KEY[:8]}...")
print(f"Secret starts: {API_SECRET[:8]}...")

async def test():
    params = {"timestamp": int(time.time() * 1000)}
    query = urlencode(params)
    sig = hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    params["signature"] = sig

    conn = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(
        connector=conn, headers={"X-MBX-APIKEY": API_KEY}
    ) as s:
        url = "https://fapi.binance.com/fapi/v2/balance"
        async with s.get(url, params=params) as r:
            data = await r.json()
            if isinstance(data, dict) and "code" in data:
                print(f"\nERROR: {data}")
                if data["code"] == -2015:
                    print("\n>> API KEY is invalid or not for Futures")
                elif data["code"] == -1022:
                    print("\n>> API SECRET is wrong (signature mismatch)")
            else:
                print(f"\nSUCCESS! Found {len(data)} assets")

asyncio.run(test())
