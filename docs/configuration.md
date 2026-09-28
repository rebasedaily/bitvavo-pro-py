# Configuration

All options are keyword arguments on `Bitvavo(...)` and `AsyncBitvavo(...)`:

| Argument | Default | Description |
|---|---|---|
| `api_key`, `api_secret` | `None` | Credentials. Give both or neither. |
| `operator_id` | `None` | Default `operatorId` for order requests. |
| `base_url` | `https://api.bitvavo.com/v2` | API root. The path part (`/v2`) is included in signatures. |
| `timeout` | `10.0` | Seconds per request. |
| `access_window_ms` | `10000` | `Bitvavo-Access-Window`, from 100 to 60000. A request that reaches Bitvavo later than this is rejected. |
| `max_retries` | `2` | Retries for transient failures. See [Error handling](errors.md#retries). |
| `retry_backoff` | `0.5` | Base retry delay in seconds, doubled on each attempt. |
| `rate_limit_buffer` | `20` | Weight points to keep in reserve. |
| `wait_on_rate_limit` | `True` | Sleep until the window resets instead of spending the reserve. |
| `user_agent` | `bitvavo-sdk-python/<ver> python/<ver>` | `User-Agent` header. |
| `http_client` | new client | Your own `httpx.Client` / `httpx.AsyncClient`. |

`Bitvavo.from_env(**overrides)` reads `BITVAVO_API_KEY`, `BITVAVO_API_SECRET`, `BITVAVO_OPERATOR_ID` and `BITVAVO_BASE_URL`.

## Lifecycle

Clients hold a connection pool, which keeps latency low for bots. Reuse one client for the lifetime of your program, and close it when you're done:

```python
with Bitvavo.from_env() as client:
    ...

# or
client = Bitvavo.from_env()
try:
    ...
finally:
    client.close()
```

## Proxies, TLS, HTTP/2 and connection limits

Pass a pre-configured `httpx` client. The SDK won't close a client it didn't create.

```python
import httpx
from bitvavo_sdk import Bitvavo

http = httpx.Client(
    proxy="http://proxy.internal:3128",
    timeout=httpx.Timeout(5.0, connect=2.0),
    limits=httpx.Limits(max_keepalive_connections=10),
)
client = Bitvavo.from_env(http_client=http)
```

## Logging

The SDK logs to the `bitvavo_sdk` logger. At `DEBUG` level it logs one line per request with method, path, status, latency, weight and remaining budget. Credentials are never logged.

```python
import logging

logging.basicConfig(level=logging.INFO)
logging.getLogger("bitvavo_sdk").setLevel(logging.DEBUG)
logging.getLogger("httpx").setLevel(logging.WARNING)  # silence httpx's own request logs
```

```
DEBUG bitvavo_sdk: GET /markets -> 200 (59 ms, weight 1, remaining 996)
```

## Calling endpoints the SDK doesn't wrap yet

`request()` signs the call, tracks the rate limit, retries and maps errors exactly like the typed methods do:

```python
client.request("GET", "/someNewEndpoint", params={"market": "BTC-EUR"}, private=True, weight=1)
```
