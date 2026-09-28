"""Poll best bid/ask for a few markets concurrently with AsyncBitvavo."""

import asyncio

from bitvavo_sdk import AsyncBitvavo

MARKETS = ["BTC-EUR", "ETH-EUR", "SOL-EUR"]


async def main() -> None:
    async with AsyncBitvavo() as client:
        for _ in range(3):
            books = await asyncio.gather(*(client.get_ticker_book(m) for m in MARKETS))
            print("  ".join(f"{b['market']} {b['bid']}/{b['ask']}" for b in books))
            await asyncio.sleep(1)


asyncio.run(main())
