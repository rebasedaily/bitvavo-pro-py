# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-10-01

### Added
- WebSocket API support:
  - `AsyncBitvavoWebSocket` (asyncio) and `BitvavoWebSocket` (background thread with callbacks).
  - Every typed REST method also works over the socket, sent as the equivalent WebSocket action.
  - Subscriptions to `ticker`, `ticker24h`, `book`, `trades`, `candles` and the private `account` channel. Multiple subscriptions to the same stream are reference-counted.
  - `watch_order_book()` / `LocalOrderBook`: a snapshot plus nonce-ordered deltas, with automatic resync after gaps and reconnects.
  - Automatic reconnect with backoff, re-authentication, resubscription and an `on_reconnect` hook. In-flight requests fail and are never resent.
  - WebSocket errors raise the same exception classes as REST.
- `websockets` is now a runtime dependency.

## [0.1.0] - 2026-09-28

### Added
- `Bitvavo` (sync) and `AsyncBitvavo` (asyncio) clients covering all 31 Bitvavo REST v2 endpoints.
- HMAC-SHA256 request signing, verified against Bitvavo's documented test vector.
- Automatic clock re-sync on errorCode 304, and `sync_time()`.
- Rate-limit tracking from `bitvavo-ratelimit-*` headers, with a pre-emptive wait before the budget runs out.
- Retry policy that never duplicates order-changing requests.
- Exception hierarchy mapped from HTTP status and Bitvavo `errorCode`.
- `TypedDict` response types, `py.typed`, strict mypy.
- Helpers: `round_to_tick`, `round_to_decimals`, `format_number`.
- `find_order()`: order lookup that tolerates Bitvavo's short indexing delay after an order is created.
