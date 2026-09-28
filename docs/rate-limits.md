# Rate limits

Bitvavo gives each account (or each IP address, when unauthenticated) **1000 weight points per minute**. Each endpoint has a weight, listed in the [endpoint reference](endpoints.md). If you go over the limit, Bitvavo returns HTTP 429 with errorCode 105 and blocks you for the rest of that minute **plus one more**. Unauthenticated IP addresses are blocked for 15 minutes.

## What the SDK does

Every response carries `bitvavo-ratelimit-limit`, `-remaining` and `-resetat` headers, and the client records them:

```python
client.get_markets()
client.rate_limit
# RateLimitState(limit=1000, remaining=992, reset_at=1790586540000)
client.rate_limit.seconds_until_reset()
```

Before each request, the client checks whether spending that endpoint's weight would leave fewer than `rate_limit_buffer` points (default 20). If it would, the client **sleeps until `reset_at`** and then sends the request. You get a short pause instead of a ban lasting over a minute.

Set `wait_on_rate_limit=False` to never sleep. The client then sends immediately, and you manage the budget yourself.

If you're blocked anyway, for example because another process shares the key, you get `RateLimitError` with `reset_at`. The next call on the same client waits automatically.

## Budgeting tips

- Prefer the all-markets endpoints: `get_ticker_books()` costs **1** point for every market, while one `get_ticker_book(m)` per market costs N.
- The expensive calls are `get_tickers_24h()` (25), `get_open_orders()` without a market (100), `cancel_orders()` without a market (100) and `atomic_cancel_orders()` (100).
- Polling `get_markets()` once a second costs 60 points per minute.
- The budget is per account and is shared by every process using the account's keys.
