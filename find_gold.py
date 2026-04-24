import aiohttp, asyncio

async def find_gold():
    conn = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=conn) as s:
        async with s.get("https://fapi.binance.com/fapi/v1/exchangeInfo") as r:
            data = await r.json()
            gold = [sym for sym in data["symbols"] 
                    if "GOLD" in sym["symbol"] or "XAU" in sym["symbol"] or "PAXG" in sym["symbol"]]
            for g in gold:
                print(f"{g['symbol']} | Status: {g['status']} | Leverage: {g.get('maxLeverage', '?')}x")
                brackets = g.get("leverageBrackets", [])
                filters = {f["filterType"]: f for f in g.get("filters", [])}
                if "LOT_SIZE" in filters:
                    ls = filters["LOT_SIZE"]
                    print(f"  Lot: min={ls['minQty']} step={ls['stepSize']}")
                if "MIN_NOTIONAL" in filters:
                    mn = filters["MIN_NOTIONAL"]
                    print(f"  Min notional: {mn.get('notional', mn)}")
            if not gold:
                print("No gold symbols found. Searching broader...")
                for sym in data["symbols"]:
                    if sym["status"] == "TRADING":
                        name = sym["symbol"]
                        if any(k in name for k in ["GOLD", "XAU", "PAXG"]):
                            print(f"  {name}")

asyncio.run(find_gold())
