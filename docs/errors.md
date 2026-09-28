# Error handling

Every exception raised by the SDK is a `BitvavoError`:

```
BitvavoError
├── MissingCredentialsError      private endpoint called without api_key/api_secret
├── TransportError               no HTTP response (DNS, connect, TLS, timeout)
└── APIError                     Bitvavo returned a non-2xx status
    ├── BadRequestError          400: invalid parameters, order rejected
    │   └── InsufficientBalanceError   errorCode 216 / 408
    ├── AuthenticationError      403, errorCode 300-309
    ├── PermissionDeniedError    403, other codes (permissions, locked account)
    ├── NotFoundError            404, e.g. 240: order does not exist or is no longer active
    ├── MarketNotTradingError    409 / errorCode 423-426, 431: market halted, auction, cancelOnly
    ├── RateLimitError           429 / 105, has .reset_at (ms epoch)
    └── ServerError              5xx
```

Every `APIError` carries `status_code`, `error_code`, `message`, `body` (the parsed JSON) and `response` (the `httpx.Response`):

```python
from bitvavo_sdk import APIError, InsufficientBalanceError, MarketNotTradingError

try:
    client.market_buy("NEW-EUR", amount_quote="25")
except InsufficientBalanceError:
    top_up()
except MarketNotTradingError as e:
    print("not open yet:", e.error_code)  # 425 = auction phase
except APIError as e:
    print(e.status_code, e.error_code, e.message)
```

The full list of codes is in the [Bitvavo documentation](https://docs.bitvavo.com/docs/errors/).

## Retries

Retrying an order request blindly can **buy twice**. The SDK therefore retries only when it's provably safe:

| Situation | GET | POST / PUT / DELETE |
|---|---|---|
| Network error, no response | retried | **raises `TransportError`** |
| HTTP 5xx | retried | raises `ServerError` |
| errorCode 107 (overloaded) or 111 (matching engine unavailable) | retried | retried: Bitvavo didn't process it |
| errorCode 109 (timeout, outcome unknown) | retried | **raises**: the order may exist |
| errorCode 304 (clock drift) | clock re-synced, retried once | same |
| 429 rate limited | raises `RateLimitError` | raises |
| 4xx | raises | raises |

Retries back off at `retry_backoff × 2^(n-1)` seconds, up to `max_retries` times.

### Handling an unknown outcome

Pass your own `client_order_id` so you can look the order up after a `TransportError` or errorCode 109. Use `find_order()` for the lookup, not `get_order()`:

```python
import uuid
from bitvavo_sdk import ServerError, TransportError

coid = str(uuid.uuid4())
try:
    order = client.market_buy("BTC-EUR", amount_quote="10", client_order_id=coid)
except (TransportError, ServerError):
    order = client.find_order("BTC-EUR", client_order_id=coid)  # waits up to 3 s
    if order is None:
        order = client.market_buy("BTC-EUR", amount_quote="10", client_order_id=coid)
```

!!! warning "`GET /order` lags behind order creation"
    In live testing, Bitvavo answered `GET /order` with errorCode 240 ("No active order found") for about 0.2–0.5 s after an order was created, even though the order was already on the book and listed by `get_open_orders()`. A single `get_order()` returning `NotFoundError` right after placing an order does **not** prove the order doesn't exist, and resending on that basis can create a duplicate. `find_order()` retries for `wait` seconds (default 3) before it returns `None`.

    The same lag applies after a cancel: `get_order()` can still show `new` for a moment. To read an order's final state, including any fill that landed just before the cancel, use `find_order(market, order_id=..., status={"canceled", "filled"})`.
