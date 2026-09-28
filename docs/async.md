# Async usage

`AsyncBitvavo` has exactly the same methods, arguments and return types as `Bitvavo`, except that each one is a coroutine:

```python
import asyncio
from bitvavo_sdk import AsyncBitvavo


async def main():
    async with AsyncBitvavo.from_env() as client:
        # fan out: one round-trip of latency instead of three
        balance, open_orders, book = await asyncio.gather(
            client.get_balance("EUR"),
            client.get_open_orders("BTC-EUR"),
            client.get_order_book("BTC-EUR", depth=5),
        )

        order = await client.market_buy("BTC-EUR", amount_quote="10")

        async for tx in client.iter_transaction_history(type="buy"):
            print(tx["executedAt"], tx["receivedAmount"])


asyncio.run(main())
```

Notes:

- Create the client inside the running event loop and reuse it. Close it with `async with` or `await client.close()`.
- Rate-limit waits use `asyncio.sleep`, so they don't block other tasks.
- The rate-limit budget is shared by all concurrent requests on the client. Each request reserves its weight before it's sent.
- To pass your own `httpx.AsyncClient`, use `http_client=`.

## How the two clients stay identical

Endpoint code is written once, as synchronous code, in `src/bitvavo_sdk/_endpoints.py`. The script `scripts/generate_async.py` produces `_async_endpoints.py` from it by adding `async`/`await` (the "unasync" technique used by `httpcore`). A test fails if the generated file is stale, and another asserts that both clients expose the same public methods.
