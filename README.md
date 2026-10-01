# bitvavo-sdk

A Python SDK for the [Bitvavo](https://bitvavo.com) Exchange REST and WebSocket APIs, with typed sync and async clients.

```python
from bitvavo_sdk import Bitvavo

client = Bitvavo.from_env()  # BITVAVO_API_KEY, BITVAVO_API_SECRET, BITVAVO_OPERATOR_ID

client.get_ticker_price("BTC-EUR")  # {'market': 'BTC-EUR', 'price': '72715'}
client.market_buy("BTC-EUR", amount_quote="10")
client.get_balance("BTC")
```

- **Complete REST coverage.** The SDK wraps all 31 REST endpoints (market data, trading, account, transfers, MiCA reports) as documented methods. `client.request()` covers anything newer.
- **WebSocket streaming.** Tickers, trades, candles and your own order and fill events arrive as async iterators or callbacks. A self-healing local order book is included, and reconnects re-authenticate and resubscribe automatically. Every REST method also works over the socket.
- **Sync and async.** `Bitvavo` and `AsyncBitvavo` expose identical methods. The async client is generated from the sync source, so the two can't drift apart.
- **Typed.** Responses are described with `TypedDict`s, and the package ships `py.typed` and passes `mypy --strict`.
- **Correct signing.** It implements Bitvavo's HMAC-SHA256 scheme and is verified against the test vector in Bitvavo's documentation. Clock drift (errorCode 304) is detected and fixed automatically.
- **Rate-limit aware.** The client tracks the `bitvavo-ratelimit-*` headers and pauses before it would get your key blocked.
- **Safe retries.** Reads retry on network errors and 5xx responses. Order requests retry only when Bitvavo guarantees the request wasn't processed. Anything ambiguous raises, so the SDK never places a duplicate order.
- **Useful errors.** `InsufficientBalanceError`, `MarketNotTradingError`, `RateLimitError` and others carry `error_code`, `status_code` and the raw response.
- **Decimal-safe.** Numbers are sent as plain decimal strings (`1e-05` becomes `"0.00001"`). Helpers round prices to `tickSize` and amounts to `quantityDecimals`.

Python 3.9+ · two runtime dependencies ([httpx](https://www.python-httpx.org/), [websockets](https://websockets.readthedocs.io/)).

## Install

```bash
pip install bitvavo-sdk
```

## Quick start

### Public market data (no API key)

```python
from bitvavo_sdk import Bitvavo

with Bitvavo() as client:
    markets = client.get_markets()
    book = client.get_order_book("BTC-EUR", depth=10)
    candles = client.get_candles("ETH-EUR", "1h", limit=24)
```

### Trading

Create an API key in the Bitvavo dashboard with the **View** and **Trade** permissions and an IP allow-list. Bitvavo requires an `operatorId` on every order. It's an integer that identifies the trader or bot within your account.

```python
from bitvavo_sdk import Bitvavo, InsufficientBalanceError, round_to_tick

client = Bitvavo(api_key, api_secret, operator_id=1001)

market = client.get_market("BTC-EUR")
price = round_to_tick("65000.37", market["tickSize"])  # Decimal('65000')

try:
    order = client.limit_buy("BTC-EUR", amount="0.001", price=price, post_only=True)
except InsufficientBalanceError:
    ...

client.update_order("BTC-EUR", order_id=order["orderId"], price="64900")
client.cancel_order("BTC-EUR", order_id=order["orderId"])
```

### Async

```python
import asyncio
from bitvavo_sdk import AsyncBitvavo


async def main():
    async with AsyncBitvavo.from_env() as client:
        btc, eth = await asyncio.gather(
            client.get_ticker_book("BTC-EUR"),
            client.get_ticker_book("ETH-EUR"),
        )


asyncio.run(main())
```

### WebSocket streaming

```python
import asyncio
from bitvavo_sdk import AsyncBitvavoWebSocket


async def main():
    async with AsyncBitvavoWebSocket() as ws:
        book = await ws.watch_order_book("BTC-EUR")  # kept in sync from deltas
        async for trade in await ws.subscribe_trades("BTC-EUR"):
            print(trade["price"], trade["amount"], "| best bid", book.best_bid)


asyncio.run(main())
```

Prefer callbacks? `BitvavoWebSocket` runs the same client on a background thread.

## Documentation

| Topic | |
|---|---|
| [Getting started](docs/getting-started.md) | Installation, API keys, first calls |
| [Configuration](docs/configuration.md) | Timeouts, retries, proxies, logging, custom `httpx` clients |
| [Authentication](docs/authentication.md) | How signing works, clock sync, key permissions |
| [Error handling](docs/errors.md) | Exception hierarchy and which errors are safe to retry |
| [Rate limits](docs/rate-limits.md) | Weights, budget tracking, avoiding bans |
| [Endpoint reference](docs/endpoints.md) | Every method with its REST route and weight |
| [Async usage](docs/async.md) | `AsyncBitvavo` patterns |
| [WebSocket API](docs/websocket.md) | Streams, local order book, reconnects, sync client |
| [Development and publishing](docs/development.md) | Tests, code generation, releasing to PyPI |

To build the docs site locally, run `pip install -e ".[docs]" && mkdocs serve`.

## Disclaimer

This is an independent project. It isn't affiliated with or endorsed by Bitvavo. Trading crypto-assets carries a high risk of loss. The software is provided as-is, without warranty (see [LICENSE](LICENSE)).
