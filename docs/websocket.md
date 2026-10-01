# WebSocket API

The WebSocket API keeps one connection open and gives you three things the REST API can't:

- **Push data.** Tickers, trades, candles and order book updates arrive as they happen. You don't have to poll.
- **Your own order and fill events** as they happen (the `account` channel).
- **Lower latency** for requests, including order placement, because there's no HTTP round trip per call.

The SDK has two WebSocket clients with the same features:

| Client | Use when |
|---|---|
| `AsyncBitvavoWebSocket` | Your program uses `asyncio`. Subscriptions are async iterators. |
| `BitvavoWebSocket` | Your program is synchronous. The client runs in a background thread and subscriptions call your callbacks. |

## Same methods as the REST client

Both WebSocket clients have **every typed method of the REST client**, with the same names, arguments and return values. The SDK sends each call as the equivalent WebSocket action (`get_markets()` becomes `getMarkets`, `create_order()` becomes `privateCreateOrder`, and so on). Code written against `Bitvavo` or `AsyncBitvavo` works on a WebSocket client unchanged.

```python
from bitvavo_sdk import AsyncBitvavoWebSocket

async with AsyncBitvavoWebSocket.from_env() as ws:  # authenticates on connect
    book = await ws.get_order_book("BTC-EUR", depth=5)
    order = await ws.limit_buy("BTC-EUR", "0.001", "60000", post_only=True)
    await ws.cancel_order("BTC-EUR", order_id=order["orderId"])
```

A few REST endpoints don't exist on the WebSocket API (`get_staking_balance`, `get_order_book_report`, `get_trades_report`). Calling them raises `NotAvailableOverWebSocket`; use the REST client for those.

Errors are the same exception classes as on REST (see [Error handling](errors.md)): `InsufficientBalanceError`, `NotFoundError` and so on. A request that gets no answer within `request_timeout` raises `TransportError`. For an order action, that means the outcome is unknown, so use `find_order()` before you retry.

## Streaming subscriptions

```python
async with AsyncBitvavoWebSocket() as ws:  # public channels need no key
    async with await ws.subscribe_trades(["BTC-EUR", "ETH-EUR"]) as trades:
        async for trade in trades:
            print(trade["market"], trade["side"], trade["amount"], "@", trade["price"])
```

| Method | Channel | Each event |
|---|---|---|
| `subscribe_ticker(markets)` | `ticker` | Best bid/ask changes. **Only the fields that changed** are included. |
| `subscribe_ticker24h(markets)` | `ticker24h` | 24h statistics, about once per second per market |
| `subscribe_trades(markets)` | `trades` | Every public trade (`event: "trade"`) |
| `subscribe_candles(markets, intervals)` | `candles` | Candle updates; `candle` is `[[ts, open, high, low, close, volume]]` |
| `subscribe_book(markets)` | `book` | Raw order book deltas. Most people want `watch_order_book()` instead. |
| `subscribe_account(markets="*")` 🔒 | `account` | Your `order` and `fill` events, for all markets by default |

Each call returns a `Subscription`:

- `async for event in sub`, or `await sub.get(timeout=...)`, reads events.
- `await sub.unsubscribe()` stops it. So does leaving an `async with` block.
- `sub.dropped` counts events that were dropped because you consumed them too slowly. Each subscription buffers up to `queue_size` events (default 10,000), and the oldest are dropped first.

Several subscriptions can share a channel and market. The client subscribes on the server once, delivers each event to every matching subscription, and unsubscribes on the server only when the last one stops.

## Local order book

`watch_order_book()` keeps a correct local copy of a market's order book:

```python
book = await ws.watch_order_book("BTC-EUR")

book.best_bid  # (Decimal('74143'), Decimal('0.0119'))
book.best_ask
book.spread, book.mid_price
book.bids(depth=10)  # [(price, size), ...], best first
book.asks(depth=10)
book.is_synced  # False briefly while it resyncs

await ws.stop_watching(book)
```

The client does the work that's easy to get wrong by hand:

1. It subscribes to the `book` channel before it loads the snapshot, so no update is lost in between.
2. It loads a snapshot (`depth`, default 1000 levels) and drops any buffered update that the snapshot already contains.
3. It applies updates strictly in `nonce` order. Bitvavo increments the nonce by exactly 1 for each change.
4. On a **nonce gap**, or after a **reconnect**, it reloads the snapshot automatically.
5. It keys prices as `Decimal`, because Bitvavo sends the same level as `"74133"` in snapshots and as `"74133.00"` in updates. String keys would treat those as two different levels.

Pass `on_update=callback` to be called with the book after every change. Reads are thread-safe.

## Reconnects

If the connection drops, the client reconnects with exponential backoff (up to `max_reconnect_delay` seconds). It then **re-authenticates and restores every subscription**, and watched order books resync on their own.

Two things can't be recovered automatically:

- **Requests that were in flight** when the connection dropped fail with `TransportError`. They're never resent automatically, so an order can't be placed twice.
- **Events published while you were disconnected** are lost. Use `on_reconnect` to catch up, for example by re-reading open orders:

```python
async def resync():
    open_orders = await ws.get_open_orders("BTC-EUR")
    ...


ws = AsyncBitvavoWebSocket.from_env(on_reconnect=resync)
```

`ws.reconnects` counts successful reconnects. Pass `reconnect=False` to end every subscription when the connection drops instead.

## Synchronous client

`BitvavoWebSocket` runs the async client on a background thread. Its request methods block until Bitvavo answers, and its subscriptions take a callback:

```python
import time
from bitvavo_sdk import BitvavoWebSocket

with BitvavoWebSocket.from_env() as ws:
    ws.subscribe_ticker24h(["BTC-EUR"], lambda e: print(e["market"], e["last"]))
    ws.subscribe_account(lambda e: print(e["event"], e["orderId"], e.get("status")))
    book = ws.watch_order_book("ETH-EUR")

    print(ws.get_balance("EUR"))  # blocking request over the socket
    time.sleep(30)
    print(book.best_bid, book.best_ask)
```

Callbacks run **on the WebSocket thread**:

- Keep them short. A slow callback delays every other event.
- Don't call blocking client methods from inside a callback. That would deadlock, so the client raises `RuntimeError` instead. Hand the work to a queue or another thread.

## Options

`AsyncBitvavoWebSocket(...)` and `BitvavoWebSocket(...)` take:

| Argument | Default | Description |
|---|---|---|
| `api_key`, `api_secret` | `None` | Needed for private actions and the `account` channel |
| `operator_id` | `None` | Default `operatorId` for order actions |
| `url` | `wss://ws.bitvavo.com/v2/` | Endpoint |
| `request_timeout` | `10.0` | Seconds to wait for a response to an action |
| `access_window_ms` | `10000` | Validity window of the authentication message |
| `reconnect` | `True` | Reconnect automatically |
| `max_reconnect_delay` | `30.0` | Upper bound of the reconnect backoff, in seconds |
| `ping_interval` | `20.0` | Keep-alive ping interval, in seconds |
| `queue_size` | `10000` | Per-subscription event buffer |
| `on_reconnect` | `None` | Function or coroutine called after a reconnect is restored |

`from_env()` reads the same environment variables as the REST client.

## Rate limits

WebSocket actions use the same weight points as their REST equivalents, and they count against the same 1000-points-per-minute budget. Bitvavo doesn't report the remaining budget over WebSocket, so the WebSocket clients can't pause automatically the way the REST client does. Separately, each connection may send at most 5000 messages per second.

To send any action the SDK doesn't wrap yet, use `await ws.request_action("someAction", market="BTC-EUR")`.
