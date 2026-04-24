import aiohttp, asyncio, time

async def test():
    conn = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=conn) as s:
        async with s.get("https://fapi.binance.com/fapi/v1/time") as r:
            data = await r.json()
            local = int(time.time() * 1000)
            server = data["serverTime"]
            diff = local - server
            print(f"Server time: {server}")
            print(f"Local time:  {local}")
            print(f"Diff (ms):   {diff}")
            if abs(diff) > 1000:
                print("WARNING: Clock out of sync!")
            else:
                print("Clock OK")

asyncio.run(test())
