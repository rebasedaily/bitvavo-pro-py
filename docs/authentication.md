# Authentication

The SDK signs requests for you. This page explains what it does, for debugging and for people porting it.

## Headers

| Header | Value |
|---|---|
| `Bitvavo-Access-Key` | Your API key |
| `Bitvavo-Access-Timestamp` | Unix time in **milliseconds** |
| `Bitvavo-Access-Signature` | HMAC-SHA256 (hex) of the string below, keyed with your API secret |
| `Bitvavo-Access-Window` | Optional validity window in ms (default 10000, max 60000) |

The signed string is the concatenation, without separators, of:

```
timestamp + METHOD + /v2/path?query + body
```

- The path includes the `/v2` prefix **and the query string**, exactly as sent.
- `body` is the exact JSON string sent, or empty when there's no body.

The SDK serialises the body once, with compact separators, and sends that same string. This keeps the signed bytes and the sent bytes identical.

```python
from bitvavo_sdk import create_signature

create_signature(
    "bitvavo",
    1548172481125,
    "POST",
    "/v2/order",
    '{"market":"BTC-EUR","side":"buy","price":"5000","amount":"1.23","orderType":"limit"}',
)
# '44d022723a20973a18f7ee97398b9fdd405d2d019c8d39e24b8cc0dcb39ca016'  (Bitvavo's documented vector)
```

## Signed public requests

When the client has credentials, it signs public requests too. Bitvavo then counts them against your account's rate limit instead of your IP address's, and a ban is shorter (1 minute instead of 15).

## Clock drift

If your clock is off by more than the access window, Bitvavo answers `403` with errorCode `304`. The client then calls `GET /time` once, stores the difference in `client.time_offset_ms`, and retries the request with a corrected timestamp. Nothing was executed, so the retry is safe. You can also sync up front:

```python
offset_ms = client.sync_time()
```

## Errors

| errorCode | Meaning |
|---|---|
| 300 | Endpoint needs authentication |
| 302 / 303 | Timestamp not in ms / access window out of range |
| 304 | Request arrived outside the access window (handled automatically) |
| 305 / 306 | Key inactive or not confirmed |
| 307 | IP address not on the key's allow-list |
| 308 / 309 | Malformed / wrong signature |
| 310 / 311 / 312 | Key lacks Trade / View / Withdraw permission |

Codes 300 to 309 raise `AuthenticationError`. Permission and account problems raise `PermissionDeniedError`.
