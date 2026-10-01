# Endpoint reference

Every Bitvavo REST endpoint and the SDK method that calls it. The same methods are available on the [WebSocket clients](websocket.md), except the staking balance and MiCA report endpoints. The weight is what the call costs against the 1000 points per minute (see [Rate limits](rate-limits.md)). 🔒 = requires an API key. All arguments after the first positional ones are keyword-only and use `snake_case`. The SDK converts them to Bitvavo's `camelCase`.

## General

| Method | Route | Weight |
|---|---|---|
| `get_time()` | `GET /time` | 1 |
| `sync_time()` | `GET /time`, stores `time_offset_ms` | 1 |
| `get_markets()` / `get_market(market)` | `GET /markets` | 1 |
| `get_assets()` / `get_asset(symbol)` | `GET /assets` | 1 |

## Market data

| Method | Route | Weight |
|---|---|---|
| `get_order_book(market, depth=)` | `GET /{market}/book` | 1 |
| `get_trades(market, limit=, start=, end=, trade_id_from=, trade_id_to=)` | `GET /{market}/trades` | 5 |
| `get_candles(market, interval, limit=, start=, end=)` | `GET /{market}/candles` | 1 |
| `get_ticker_prices()` / `get_ticker_price(market)` | `GET /ticker/price` | 1 |
| `get_ticker_books()` / `get_ticker_book(market)` | `GET /ticker/book` | 1 |
| `get_tickers_24h()` / `get_ticker_24h(market)` | `GET /ticker/24h` | 25 / 1 |
| `get_order_book_report(market, depth=)` | `GET /report/{market}/book` (MiCA) | 1 |
| `get_trades_report(market, ...)` | `GET /report/{market}/trades` (MiCA) | 5 |

Candle intervals: `1m 5m 15m 30m 1h 2h 4h 6h 8h 12h 1d 1W 1M`. Candles are `[timestamp, open, high, low, close, volume]`, newest first.

## Trading 🔒

| Method | Route | Weight |
|---|---|---|
| `create_order(market, side, order_type, ...)` | `POST /order` | 1 |
| `market_buy(market, amount= \| amount_quote=)` | `POST /order` | 1 |
| `market_sell(market, amount= \| amount_quote=)` | `POST /order` | 1 |
| `limit_buy(market, amount, price, ...)` | `POST /order` | 1 |
| `limit_sell(market, amount, price, ...)` | `POST /order` | 1 |
| `update_order(market, order_id= \| client_order_id=, ...)` | `PUT /order` | 1 |
| `cancel_order(market, order_id= \| client_order_id=)` | `DELETE /order` | 1 |
| `cancel_orders(market=None)` | `DELETE /orders` | 25 / 100 |
| `atomic_cancel_orders(market, side)` | `DELETE /atomic/orders` | 100 |
| `cancel_orders_after(cod_group_id, expiry_after_seconds)` | `POST /cancelOrdersAfter` | 5 |
| `get_order(market, order_id= \| client_order_id=)` | `GET /order` | 1 |
| `find_order(market, order_id= \| client_order_id=, wait=3.0)` | `GET /order`, retried while Bitvavo's view lags (after create/cancel); `status=` waits for a final state | 1 per attempt |
| `get_orders(market, limit=, start=, end=, order_id_from=, order_id_to=)` | `GET /orders` | 5 |
| `get_open_orders(market=None, base=None)` | `GET /ordersOpen` | 5 / 100 |
| `get_trade_history(market, ...)` | `GET /trades` | 5 |

`create_order` keyword arguments:

| Argument | Bitvavo field | Notes |
|---|---|---|
| `amount` | `amount` | Base quantity, at most `quantityDecimals` decimals |
| `amount_quote` | `amountQuote` | Quote quantity (market / stopLoss / takeProfit orders) |
| `price` | `price` | A multiple of `tickSize` |
| `trigger_amount`, `trigger_type`, `trigger_reference` | `trigger*` | For stop and take-profit orders |
| `time_in_force` | `timeInForce` | `GTC` (default), `IOC`, `FOK` |
| `post_only` | `postOnly` | Maker-only |
| `self_trade_prevention` | `selfTradePrevention` | `decrementAndCancel` (default), `cancelOldest`, `cancelNewest`, `cancelBoth` |
| `client_order_id` | `clientOrderId` | Your UUID. Use it to recover from unknown outcomes |
| `response_required` | `responseRequired` | `False` gives a smaller, faster response |
| `cod_group_id` | `codGroupId` | Cancel-on-disconnect group |
| `operator_id` | `operatorId` | Overrides the client default. **Required by Bitvavo** |

Numbers can be `str`, `int`, `float` or `Decimal`, and are sent as plain decimal strings.

## Account 🔒

| Method | Route | Weight |
|---|---|---|
| `get_account()` | `GET /account` | 1 |
| `get_market_fees(market=None, quote=None)` | `GET /account/fees` | 1 |
| `get_balance(symbol=None)` | `GET /balance` | 5 |
| `get_staking_balance(symbol=None)` | `GET /stakingBalance` | 5 |
| `get_transaction_history(from_date=, to_date=, page=, max_items=, type=)` | `GET /account/history` | 1 |
| `iter_transaction_history(...)` | all pages of the above | 1 per page |

## Transfers 🔒

| Method | Route | Weight |
|---|---|---|
| `get_deposit_data(symbol)` | `GET /deposit` | 1 |
| `get_deposit_history(symbol=None, ...)` | `GET /depositHistory` | 5 |
| `get_withdrawal_history(symbol=None, ...)` | `GET /withdrawalHistory` | 5 |
| `withdraw(symbol, amount, address, payment_id=, add_withdrawal_fee=)` | `POST /withdrawal` | 1 |
| `withdraw_crypto(asset, network, address, amount, idempotency_key=, ...)` | `POST /crypto/withdrawal` | 25 |

> API withdrawals skip 2FA and e-mail confirmation. Always pass `idempotency_key` to `withdraw_crypto` so a retried request can't pay out twice.

## Helpers

| Function | Purpose |
|---|---|
| `round_to_tick(price, tick_size, rounding="nearest"\|"down"\|"up")` | Valid limit price (avoids errorCode 422) |
| `round_to_decimals(amount, decimals, rounding="down")` | Valid amount (avoids errorCode 429) |
| `format_number(x)` | Plain decimal string, as sent on the wire |
| `create_signature(secret, ts, method, path, body)` | Raw request signing |

## Response types

`bitvavo_sdk.types` defines a `TypedDict` for every response (`Market`, `Order`, `Fill`, `Balance`, `OrderBook`, `TickerBook`, ...), plus `Literal` types for enums (`Side`, `OrderType`, `MarketStatus`, `OrderStatus`, `CandleInterval`, ...). Market statuses are `trading`, `halted`, `auction`, `auctionMatching` and `cancelOnly`.
