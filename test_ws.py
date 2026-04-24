import aiohttp, asyncio, json

async def test_ws():
    url = "wss://fstream.binance.com/ws/btcusdt@kline_1m"
    print(f"Connecting to {url}...")
    conn = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=conn) as s:
        async with s.ws_connect(url, heartbeat=20, ssl=False) as ws:
            print("Connected! Waiting for messages...")
            count = 0
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    k = data.get("k", {})
                    print(f"#{count} | {data.get('s','?')} | close={k.get('c','?')} | closed={k.get('x','?')}")
                    count += 1
                    if count >= 3:
                        break
    print("Done - BTC stream works!")

asyncio.run(test_ws())
