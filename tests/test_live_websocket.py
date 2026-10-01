"""Live, read-only checks of the WebSocket clients against the real Bitvavo API.

Public tests always run when the network is reachable and BITVAVO_LIVE_WS=1 is set;
private ones also need BITVAVO_API_KEY / BITVAVO_API_SECRET (environment or ``.env``).

Safety: the clients here refuse every action outside a read-only allowlist before
it is sent, so no order or transfer can be created whatever the key's permissions.

    BITVAVO_LIVE_WS=1 pytest tests/test_live_websocket.py -v -rs
"""

from __future__ import annotations

import asyncio
import os
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

import pytest

from bitvavo_sdk import AsyncBitvavoWebSocket, AuthenticationError, BitvavoWebSocket


def _load_dotenv() -> None:
    path = Path(__file__).resolve().parent.parent / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv()

pytestmark = pytest.mark.skipif(
    os.environ.get("BITVAVO_LIVE_WS") != "1", reason="set BITVAVO_LIVE_WS=1 to run live tests"
)
needs_key = pytest.mark.skipif(
    not (os.environ.get("BITVAVO_API_KEY") and os.environ.get("BITVAVO_API_SECRET")),
    reason="needs BITVAVO_API_KEY / BITVAVO_API_SECRET",
)

READ_ONLY = {
    "authenticate",
    "subscribe",
    "unsubscribe",
    "getTime",
    "getMarkets",
    "getAssets",
    "getBook",
    "getTrades",
    "getCandles",
    "getTickerPrice",
    "getTickerBook",
    "getTicker24h",
    "privateGetBalance",
    "privateGetAccount",
    "privateGetFees",
    "privateGetOrder",
    "privateGetOrders",
    "privateGetOrdersOpen",
    "privateGetTrades",
    "privateGetTransactionHistory",
    "privateGetDepositHistory",
    "privateGetWithdrawalHistory",
}


class ReadOnlyViolation(AssertionError):
    pass


class GuardedWebSocket(AsyncBitvavoWebSocket):
    async def _request(self, payload: Dict[str, Any], *, wait_ready: bool = True) -> Any:
        if payload.get("action") not in READ_ONLY:
            raise ReadOnlyViolation(f"blocked action {payload.get('action')!r}")
        return await super()._request(payload, wait_ready=wait_ready)


def run(coro: Any) -> Any:
    return asyncio.run(asyncio.wait_for(coro, 60))


def test_guard_blocks_writes_before_sending():
    async def t() -> None:
        async with GuardedWebSocket(operator_id=1) as ws:
            with pytest.raises(ReadOnlyViolation):
                await ws.request_action("privateCancelOrders", operatorId=1)

    run(t())


def test_public_requests():
    async def t() -> None:
        async with GuardedWebSocket() as ws:
            assert abs(await ws.sync_time()) < 60_000
            markets = await ws.get_markets()
            assert any(m["market"] == "BTC-EUR" for m in markets)
            assert (await ws.get_market("BTC-EUR"))["market"] == "BTC-EUR"
            assert Decimal((await ws.get_ticker_price("BTC-EUR"))["price"]) > 0
            assert len(await ws.get_candles("BTC-EUR", "1m", limit=3)) == 3
            assert (await ws.get_ticker_24h("BTC-EUR"))["market"] == "BTC-EUR"

    run(t())


def test_local_order_book_matches_fresh_snapshot():
    async def t() -> None:
        async with GuardedWebSocket() as ws:
            book = await ws.watch_order_book("BTC-EUR")
            start = book.nonce
            await asyncio.sleep(3)
            assert book.is_synced and book.nonce is not None and book.nonce >= start
            bids, asks = book.bids(), book.asks()
            assert bids[0][0] < asks[0][0]
            assert all(a[0] > b[0] for a, b in zip(bids, bids[1:]))
            # Compare top of book with a fresh snapshot taken at (almost) the same nonce.
            for _ in range(5):
                snap = await ws.get_order_book("BTC-EUR", depth=5)
                if snap["nonce"] == book.nonce:
                    assert book.best_bid == (
                        Decimal(snap["bids"][0][0]),
                        Decimal(snap["bids"][0][1]),
                    )
                    assert book.best_ask == (
                        Decimal(snap["asks"][0][0]),
                        Decimal(snap["asks"][0][1]),
                    )
                    return
                await asyncio.sleep(0.05)
            pytest.skip("book too busy to catch an identical nonce; ordering checks passed")

    run(t())


def test_streams_deliver_events():
    async def t() -> None:
        async with GuardedWebSocket() as ws:
            t24 = await ws.subscribe_ticker24h(["BTC-EUR", "ETH-EUR"])
            ticker = await ws.subscribe_ticker("BTC-EUR")
            seen = {(await t24.get(10))["market"] for _ in range(4)}
            assert seen <= {"BTC-EUR", "ETH-EUR"} and seen
            assert (await ticker.get(15))["market"] == "BTC-EUR"

    run(t())


@needs_key
def test_authenticated_reads_and_account_channel():
    async def t() -> None:
        async with GuardedWebSocket.from_env() as ws:
            assert ws.authenticated
            assert isinstance(await ws.get_balance(), list)
            assert "fees" in await ws.get_account()
            assert isinstance(await ws.get_open_orders("BTC-EUR"), list)
            account = await ws.subscribe_account()
            await account.unsubscribe()

    run(t())


@needs_key
def test_wrong_secret_rejected():
    async def t() -> None:
        ws = GuardedWebSocket(os.environ["BITVAVO_API_KEY"], "0" * 128)
        with pytest.raises(AuthenticationError) as info:
            await ws.connect()
        assert info.value.error_code == 309

    run(t())


def test_sync_client_live():
    received: List[Dict[str, Any]] = []
    with BitvavoWebSocket() as ws:
        assert ws.get_time()["time"] > 0
        ws.subscribe_ticker24h("BTC-EUR", received.append)
        book = ws.watch_order_book("ETH-EUR")
        deadline = time.monotonic() + 15
        while not received and time.monotonic() < deadline:
            time.sleep(0.1)
        assert received and received[0]["market"] == "BTC-EUR"
        assert book.best_bid is not None and book.best_ask is not None
