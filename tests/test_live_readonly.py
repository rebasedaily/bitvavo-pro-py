"""Live, read-only checks against the real Bitvavo API.

Skipped unless BITVAVO_API_KEY and BITVAVO_API_SECRET are set, either in the
environment or in a ``.env`` file at the repository root (git-ignored).

Safety: every client here uses an httpx hook that refuses any request other than
GET before it leaves the machine, so these tests can never place, change or cancel
an order or move funds, whatever permissions the key has.

    pytest tests/test_live_readonly.py -v -rs
"""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from bitvavo_sdk import AsyncBitvavo, AuthenticationError, Bitvavo, PermissionDeniedError


def _load_dotenv() -> None:
    path = Path(__file__).resolve().parent.parent / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv()

pytestmark = pytest.mark.skipif(
    not (os.environ.get("BITVAVO_API_KEY") and os.environ.get("BITVAVO_API_SECRET")),
    reason="set BITVAVO_API_KEY / BITVAVO_API_SECRET (env or .env) to run live read-only tests",
)

MARKET = "BTC-EUR"


class ReadOnlyViolation(AssertionError):
    pass


def _refuse_writes(request: httpx.Request) -> None:
    if request.method != "GET":
        raise ReadOnlyViolation(f"blocked {request.method} {request.url.path}")


async def _refuse_writes_async(request: httpx.Request) -> None:
    _refuse_writes(request)


def _client(**kwargs) -> Bitvavo:
    http = httpx.Client(timeout=10, event_hooks={"request": [_refuse_writes]})
    return Bitvavo.from_env(http_client=http, **kwargs)


@pytest.fixture(scope="module")
def live():
    c = _client()
    yield c
    c._http.close()


def _needs_permission(call):
    """Run a private call; skip (not fail) if the key lacks the permission."""
    try:
        return call()
    except PermissionDeniedError as exc:
        pytest.skip(f"key lacks permission: [{exc.error_code}] {exc.message}")


# -- the guard itself --------------------------------------------------------------


def test_guard_blocks_non_get_before_sending():
    c = _client(operator_id=1)
    with pytest.raises(ReadOnlyViolation):
        c.cancel_orders(MARKET)  # DELETE: must never reach Bitvavo


# -- authentication ------------------------------------------------------------------


def test_signed_request_accepted(live):
    account = live.get_account()
    assert {"taker", "maker", "volume"} <= set(account["fees"])
    assert live.rate_limit.limit and live.rate_limit.remaining is not None


def test_wrong_secret_is_rejected_with_auth_error():
    http = httpx.Client(timeout=10, event_hooks={"request": [_refuse_writes]})
    bad = Bitvavo(os.environ["BITVAVO_API_KEY"], "0" * 128, http_client=http)
    with pytest.raises(AuthenticationError) as info:
        bad.get_balance()
    assert info.value.error_code == 309


def test_clock_skew_is_detected_and_fixed_automatically(live):
    live.sync_time()
    real_offset = live.time_offset_ms
    live.time_offset_ms = real_offset - 60_000  # pretend our clock is a minute behind
    assert isinstance(live.get_balance(), list)  # 304 -> re-sync -> retry succeeds
    assert abs(live.time_offset_ms - real_offset) < 2_000


# -- account -------------------------------------------------------------------------


def test_balance(live):
    balances = live.get_balance()
    for b in balances:
        assert Decimal(b["available"]) >= 0 and Decimal(b["inOrder"]) >= 0
    eur = live.get_balance("EUR")
    assert all(b["symbol"] == "EUR" for b in eur)


def test_market_fees(live):
    fees = live.get_market_fees(MARKET)
    assert Decimal(fees["taker"]) >= 0 and Decimal(fees["maker"]) >= -1


def test_staking_balance(live):
    assert isinstance(live.get_staking_balance(), list)


def test_transaction_history_and_pagination(live):
    page = live.get_transaction_history(max_items=5)
    assert {"items", "currentPage", "totalPages"} <= set(page)
    first = next(iter(live.iter_transaction_history(max_items=5)), None)
    if page["items"]:
        assert first == page["items"][0]


# -- trading reads (need View + Trade permission) -------------------------------------


def test_open_orders(live):
    orders = _needs_permission(lambda: live.get_open_orders(MARKET))
    assert all(o["market"] == MARKET for o in orders)


def test_order_history(live):
    orders = _needs_permission(lambda: live.get_orders(MARKET, limit=5))
    assert len(orders) <= 5


def test_trade_history(live):
    trades = _needs_permission(lambda: live.get_trade_history(MARKET, limit=5))
    assert len(trades) <= 5


# -- transfers (reads only) ---------------------------------------------------------------


def test_deposit_and_withdrawal_history(live):
    assert isinstance(live.get_deposit_history(limit=5), list)
    assert isinstance(live.get_withdrawal_history(limit=5), list)


# -- signed public endpoints ----------------------------------------------------------


def test_signed_public_endpoints(live):
    m = live.get_market(MARKET)
    assert m["market"] == MARKET and Decimal(m["tickSize"]) > 0
    assert live.get_asset("BTC")["symbol"] == "BTC"
    book = live.get_order_book(MARKET, depth=3)
    assert Decimal(book["bids"][0][0]) < Decimal(book["asks"][0][0])
    assert len(live.get_candles(MARKET, "1h", limit=3)) == 3
    assert live.get_ticker_24h(MARKET)["market"] == MARKET
    assert len(live.get_ticker_books()) > 100


def test_async_client_live():
    async def main():
        http = httpx.AsyncClient(timeout=10, event_hooks={"request": [_refuse_writes_async]})
        async with AsyncBitvavo.from_env(http_client=http) as c:
            balance, account = await asyncio.gather(c.get_balance(), c.get_account())
            await http.aclose()
            return balance, account

    balance, account = asyncio.run(main())
    assert isinstance(balance, list) and "fees" in account
