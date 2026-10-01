"""WebSocket client tests against a local fake Bitvavo WebSocket server."""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
import time
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

import pytest
from websockets.asyncio.server import ServerConnection, serve

from bitvavo_sdk import (
    AsyncBitvavoWebSocket,
    AuthenticationError,
    BitvavoWebSocket,
    InsufficientBalanceError,
    LocalOrderBook,
    MissingCredentialsError,
    NotAvailableOverWebSocket,
    TransportError,
    create_signature,
)

from .conftest import KEY, SECRET

Handler = Callable[[Dict[str, Any]], Any]


class FakeBitvavo:
    """Speaks enough of Bitvavo's WebSocket protocol for the client under test."""

    def __init__(self) -> None:
        self.received: List[Dict[str, Any]] = []
        self.connections: List[ServerConnection] = []
        self.handlers: Dict[str, Handler] = {}
        self.auth_codes: List[int] = []  # errorCodes to answer authenticate with, in order
        self.url = ""

    def actions(self, name: str) -> List[Dict[str, Any]]:
        return [m for m in self.received if m.get("action") == name]

    async def handler(self, ws: ServerConnection) -> None:
        self.connections.append(ws)
        async for raw in ws:
            msg = json.loads(raw)
            self.received.append(msg)
            reply = self.reply(msg)
            if reply is not None:
                await ws.send(json.dumps(reply))

    def reply(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        action, rid = msg.get("action"), msg.get("requestId")
        if action == "authenticate":
            if self.auth_codes:
                code = self.auth_codes.pop(0)
                return {"action": action, "requestId": rid, "errorCode": code, "error": "x"}
            return {"event": "authenticate", "requestId": rid, "authenticated": True}
        if action in ("subscribe", "unsubscribe"):
            event = "subscribed" if action == "subscribe" else "unsubscribed"
            return {"event": event, "requestId": rid, "subscriptions": {}}
        if action in self.handlers:
            result = self.handlers[action](msg)
            if result is _NO_REPLY:
                return None
            if isinstance(result, dict) and "errorCode" in result:
                return {"action": action, "requestId": rid, **result}
            return {"action": action, "requestId": rid, "response": result}
        if action == "getTime":
            now = int(time.time() * 1000)
            return {"action": action, "requestId": rid, "response": {"time": now, "timeNs": 0}}
        return {"action": "unknown", "requestId": rid, "errorCode": 415, "error": "Invalid action."}

    async def push(self, event: Dict[str, Any]) -> None:
        for ws in list(self.connections):
            with contextlib.suppress(Exception):
                await ws.send(json.dumps(event))

    async def drop_connections(self) -> None:
        for ws in list(self.connections):
            await ws.close()
        self.connections.clear()


_NO_REPLY = object()


def run(test: Callable[[FakeBitvavo], Any]) -> Any:
    async def main() -> Any:
        fake = FakeBitvavo()
        async with serve(fake.handler, "127.0.0.1", 0) as server:
            port = next(iter(server.sockets)).getsockname()[1]
            fake.url = f"ws://127.0.0.1:{port}/v2/"
            return await asyncio.wait_for(test(fake), 15)

    return asyncio.run(main())


def client(fake: FakeBitvavo, **kwargs: Any) -> AsyncBitvavoWebSocket:
    kwargs.setdefault("request_timeout", 2.0)
    return AsyncBitvavoWebSocket(url=fake.url, **kwargs)


async def until(predicate: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


# -- authentication ------------------------------------------------------------------


def test_websocket_signature_matches_bitvavo_documentation_example():
    # Vector from https://docs.bitvavo.com/docs/websocket-api/introduction/
    sig = create_signature("bitvavo", 1548175200641, "GET", "/v2/websocket")
    assert sig == "653fc0505431c63a043273da4bd2f0927eae83948d796084f313e5d1131b0d6f"


def test_authenticates_on_connect():
    async def t(fake: FakeBitvavo) -> None:
        async with client(fake, api_key=KEY, api_secret=SECRET) as ws:
            assert ws.authenticated
        auth = fake.actions("authenticate")[0]
        assert auth["key"] == KEY and auth["window"] == 10_000
        expected = create_signature(SECRET, auth["timestamp"], "GET", "/v2/websocket")
        assert auth["signature"] == expected

    run(t)


def test_public_client_does_not_authenticate():
    async def t(fake: FakeBitvavo) -> None:
        async with client(fake) as ws:
            assert (await ws.get_time())["time"] > 0
        assert fake.actions("authenticate") == []

    run(t)


def test_bad_credentials_raise_and_close():
    async def t(fake: FakeBitvavo) -> None:
        fake.auth_codes = [309]
        ws = client(fake, api_key=KEY, api_secret=SECRET)
        with pytest.raises(AuthenticationError) as info:
            await ws.connect()
        assert info.value.error_code == 309 and not ws.connected

    run(t)


def test_clock_skew_on_auth_resyncs_and_retries():
    async def t(fake: FakeBitvavo) -> None:
        fake.auth_codes = [304]
        async with client(fake, api_key=KEY, api_secret=SECRET) as ws:
            assert ws.authenticated
        assert len(fake.actions("authenticate")) == 2
        assert len(fake.actions("getTime")) == 1

    run(t)


def test_private_action_without_credentials():
    async def t(fake: FakeBitvavo) -> None:
        async with client(fake) as ws:
            with pytest.raises(MissingCredentialsError):
                await ws.get_balance()
            with pytest.raises(MissingCredentialsError):
                await ws.subscribe_account()
        assert fake.actions("privateGetBalance") == []

    run(t)


# -- request / response ------------------------------------------------------------------


def test_typed_methods_become_actions():
    async def t(fake: FakeBitvavo) -> None:
        fake.handlers["privateCreateOrder"] = lambda m: {"orderId": "1", "status": "new"}
        fake.handlers["getBook"] = lambda m: {
            "market": m["market"],
            "nonce": 1,
            "bids": [],
            "asks": [],
        }
        fake.handlers["getTickerPrice"] = lambda m: [{"market": "BTC-EUR", "price": "1"}]
        async with client(fake, api_key=KEY, api_secret=SECRET, operator_id=7) as ws:
            order = await ws.limit_buy("BTC-EUR", 0.00001, "50000.10", post_only=True)
            book = await ws.get_order_book("BTC-EUR", depth=3)
            price = await ws.get_ticker_price("BTC-EUR")
        assert order == {"orderId": "1", "status": "new"}
        assert book["market"] == "BTC-EUR" and price == {"market": "BTC-EUR", "price": "1"}
        sent = fake.actions("privateCreateOrder")[0]
        assert {k: v for k, v in sent.items() if k != "requestId"} == {
            "action": "privateCreateOrder",
            "market": "BTC-EUR",
            "side": "buy",
            "orderType": "limit",
            "operatorId": 7,
            "amount": "0.00001",
            "price": "50000.1",
            "postOnly": True,
        }
        assert fake.actions("getBook")[0]["depth"] == 3  # path parameter moved into body

    run(t)


def test_concurrent_requests_are_matched_by_request_id():
    async def t(fake: FakeBitvavo) -> None:
        # The server answers each getBook with the market it was asked for; send many
        # concurrently and check every caller gets its own answer.
        fake.handlers["getBook"] = lambda m: {
            "market": m["market"],
            "nonce": 0,
            "bids": [],
            "asks": [],
        }
        markets = [f"M{i}-EUR" for i in range(20)]
        async with client(fake) as ws:
            books = await asyncio.gather(*(ws.get_order_book(m) for m in markets))
        assert [b["market"] for b in books] == markets

    run(t)


def test_errors_map_to_sdk_exceptions():
    async def t(fake: FakeBitvavo) -> None:
        fake.handlers["privateCreateOrder"] = lambda m: {"errorCode": 216, "error": "Insufficient"}
        async with client(fake, api_key=KEY, api_secret=SECRET, operator_id=1) as ws:
            with pytest.raises(InsufficientBalanceError) as info:
                await ws.market_buy("BTC-EUR", amount_quote=10)
        assert info.value.error_code == 216 and info.value.status_code == 400

    run(t)


def test_timeout_raises_transport_error():
    async def t(fake: FakeBitvavo) -> None:
        fake.handlers["getMarkets"] = lambda m: _NO_REPLY
        async with client(fake, request_timeout=0.3) as ws:
            with pytest.raises(TransportError, match="outcome unknown"):
                await ws.get_markets()
            assert ws._pending == {}

    run(t)


def test_rest_only_endpoint():
    async def t(fake: FakeBitvavo) -> None:
        async with client(fake, api_key=KEY, api_secret=SECRET) as ws:
            with pytest.raises(NotAvailableOverWebSocket):
                await ws.get_staking_balance()

    run(t)


def test_request_action_escape_hatch():
    async def t(fake: FakeBitvavo) -> None:
        fake.handlers["someNewAction"] = lambda m: {"echo": m["x"]}
        async with client(fake) as ws:
            assert await ws.request_action("someNewAction", x=5, y=None) == {"echo": 5}
        assert "y" not in fake.actions("someNewAction")[0]

    run(t)


# -- subscriptions ----------------------------------------------------------------------


def test_events_are_routed_to_matching_subscriptions():
    async def t(fake: FakeBitvavo) -> None:
        async with client(fake, api_key=KEY, api_secret=SECRET) as ws:
            ticker = await ws.subscribe_ticker(["BTC-EUR"])
            t24 = await ws.subscribe_ticker24h(["BTC-EUR", "ETH-EUR"])
            trades = await ws.subscribe_trades("ETH-EUR")
            candles = await ws.subscribe_candles("BTC-EUR", ["1m"])
            account = await ws.subscribe_account()
            await fake.push({"event": "ticker", "market": "ETH-EUR", "bestBid": "1"})  # not ours
            await fake.push({"event": "ticker", "market": "BTC-EUR", "bestBid": "2"})
            await fake.push(
                {
                    "event": "ticker24h",
                    "data": [
                        {"market": "BTC-EUR", "last": "3"},
                        {"market": "ETH-EUR", "last": "4"},
                    ],
                }
            )
            await fake.push({"event": "trade", "market": "ETH-EUR", "price": "5"})
            await fake.push(
                {"event": "candle", "market": "BTC-EUR", "interval": "5m", "candle": []}
            )
            await fake.push(
                {"event": "candle", "market": "BTC-EUR", "interval": "1m", "candle": [[1]]}
            )
            await fake.push({"event": "fill", "market": "XRP-EUR", "orderId": "f"})
            assert (await ticker.get(2))["bestBid"] == "2"
            assert [(await t24.get(2))["last"] for _ in range(2)] == ["3", "4"]
            assert (await trades.get(2))["price"] == "5"
            assert (await candles.get(2))["candle"] == [[1]]
            assert (await account.get(2))["orderId"] == "f"
            with pytest.raises(asyncio.TimeoutError):
                await ticker.get(0.1)  # the ETH-EUR ticker was not delivered
        sub = fake.actions("subscribe")
        assert {"name": "account", "markets": "*"} in sub[-1]["channels"]
        assert {"name": "candles", "markets": ["BTC-EUR"], "interval": ["1m"]} in sub[3]["channels"]

    run(t)


def test_shared_channel_is_reference_counted():
    async def t(fake: FakeBitvavo) -> None:
        async with client(fake) as ws:
            a = await ws.subscribe_trades("BTC-EUR")
            b = await ws.subscribe_trades(["BTC-EUR", "ETH-EUR"])
            assert len(fake.actions("subscribe")) == 2
            assert fake.actions("subscribe")[1]["channels"] == [
                {"name": "trades", "markets": ["ETH-EUR"]}  # BTC-EUR already subscribed
            ]
            await fake.push({"event": "trade", "market": "BTC-EUR", "id": "1"})
            assert (await a.get(2))["id"] == (await b.get(2))["id"] == "1"
            await a.unsubscribe()
            assert fake.actions("unsubscribe") == []  # b still needs BTC-EUR
            await b.unsubscribe()
            await until(lambda: len(fake.actions("unsubscribe")) == 1)
            channels = fake.actions("unsubscribe")[0]["channels"]
            assert sorted(channels[0]["markets"]) == ["BTC-EUR", "ETH-EUR"]
            with pytest.raises(StopAsyncIteration):
                await a.get(1)

    run(t)


def test_async_iteration_ends_on_unsubscribe():
    async def t(fake: FakeBitvavo) -> None:
        async with client(fake) as ws:
            sub = await ws.subscribe_trades("BTC-EUR")
            await fake.push({"event": "trade", "market": "BTC-EUR", "id": "1"})
            seen = []
            async for event in sub:
                seen.append(event["id"])
                await sub.unsubscribe()
            assert seen == ["1"]

    run(t)


def test_slow_consumer_drops_oldest_events():
    async def t(fake: FakeBitvavo) -> None:
        async with client(fake, queue_size=3) as ws:
            sub = await ws.subscribe_trades("BTC-EUR")
            for i in range(5):
                await fake.push({"event": "trade", "market": "BTC-EUR", "id": str(i)})
            await until(lambda: sub.dropped == 2)
            assert [(await sub.get(1))["id"] for _ in range(3)] == ["2", "3", "4"]

    run(t)


# -- reconnect --------------------------------------------------------------------------


def test_reconnect_reauthenticates_and_resubscribes():
    async def t(fake: FakeBitvavo) -> None:
        reconnected = asyncio.Event()
        ws = client(fake, api_key=KEY, api_secret=SECRET, on_reconnect=reconnected.set)
        async with ws:
            trades = await ws.subscribe_trades("BTC-EUR")
            fake.handlers["getMarkets"] = lambda m: _NO_REPLY
            pending = asyncio.create_task(ws.get_markets())
            await until(lambda: bool(fake.actions("getMarkets")))
            await fake.drop_connections()
            with pytest.raises(TransportError):
                await pending  # in-flight request fails, never silently retried
            await asyncio.wait_for(reconnected.wait(), 5)
            assert ws.reconnects == 1 and ws.authenticated
            assert len(fake.actions("authenticate")) == 2
            resub = fake.actions("subscribe")[-1]["channels"]
            assert resub == [{"name": "trades", "markets": ["BTC-EUR"]}]
            await fake.push({"event": "trade", "market": "BTC-EUR", "id": "after"})
            assert (await trades.get(2))["id"] == "after"

    run(t)


def test_no_reconnect_ends_subscriptions():
    async def t(fake: FakeBitvavo) -> None:
        async with client(fake, reconnect=False) as ws:
            sub = await ws.subscribe_trades("BTC-EUR")
            await fake.drop_connections()
            with pytest.raises(StopAsyncIteration):
                await sub.get(3)

    run(t)


# -- local order book ----------------------------------------------------------------------


def _book_handler(snapshots: List[Dict[str, Any]]) -> Handler:
    def handler(msg: Dict[str, Any]) -> Any:
        return snapshots.pop(0) if len(snapshots) > 1 else snapshots[0]

    return handler


def test_watch_order_book_applies_deltas_and_resyncs_on_gap():
    async def t(fake: FakeBitvavo) -> None:
        snap1 = {
            "market": "BTC-EUR",
            "nonce": 10,
            "bids": [["100", "1"], ["99", "2"]],
            "asks": [["101", "1"]],
        }
        snap2 = {"market": "BTC-EUR", "nonce": 50, "bids": [["90", "9"]], "asks": [["91", "9"]]}
        fake.handlers["getBook"] = _book_handler([snap1, snap2])
        updates = []
        async with client(fake) as ws:
            book = await ws.watch_order_book("BTC-EUR", on_update=lambda b: updates.append(b.nonce))
            assert book.is_synced and book.nonce == 10
            assert book.best_bid == (Decimal(100), Decimal(1))
            await fake.push(
                {"event": "book", "market": "BTC-EUR", "nonce": 9, "bids": [["1", "1"]], "asks": []}
            )
            await fake.push(
                {
                    "event": "book",
                    "market": "BTC-EUR",
                    "nonce": 11,
                    # "100.00" must hit the "100" level; size 0 removes a level
                    "bids": [["100.00", "0"], ["99.5", "3"]],
                    "asks": [["101", "0.5"]],
                }
            )
            await until(lambda: book.nonce == 11)
            assert book.bids() == [(Decimal("99.5"), Decimal(3)), (Decimal(99), Decimal(2))]
            assert book.best_ask == (Decimal(101), Decimal("0.5"))
            assert book.spread == Decimal("1.5")
            # gap: 12 is missing -> resync from a new snapshot
            await fake.push(
                {"event": "book", "market": "BTC-EUR", "nonce": 13, "bids": [], "asks": []}
            )
            await until(lambda: book.nonce == 50)
            assert book.snapshots == 2 and book.best_bid == (Decimal(90), Decimal(9))
            await ws.stop_watching(book)
            await until(lambda: bool(fake.actions("unsubscribe")))
        assert updates[:2] == [10, 11]

    run(t)


def test_local_order_book_unit():
    book = LocalOrderBook("X-EUR")
    assert book.best_bid is None and book.spread is None and not book.is_synced
    book._load_snapshot({"nonce": 5, "bids": [["10", "1"], ["11", "0"]], "asks": [["12", "2"]]})
    assert book.bids() == [(Decimal(10), Decimal(1))]  # zero-size snapshot levels skipped
    assert book._apply({"nonce": 5}) is None
    assert book._apply({"nonce": 6, "bids": [["10.0", "4"]], "asks": []}) is True
    assert book.bids() == [(Decimal(10), Decimal(4))]
    assert book.mid_price == Decimal(11)
    assert book._apply({"nonce": 8}) is False and not book.is_synced


# -- sync client --------------------------------------------------------------------------


def test_sync_client_requests_callbacks_and_book():
    fake = FakeBitvavo()
    fake.handlers["getBook"] = lambda m: {
        "market": m["market"],
        "nonce": 1,
        "bids": [["5", "1"]],
        "asks": [["6", "1"]],
    }
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    stop: Dict[str, Any] = {}

    async def serve_forever() -> None:
        async with serve(fake.handler, "127.0.0.1", 0) as server:
            fake.url = f"ws://127.0.0.1:{next(iter(server.sockets)).getsockname()[1]}/v2/"
            stop["event"] = asyncio.Event()
            ready.set()
            await stop["event"].wait()

    thread = threading.Thread(target=loop.run_until_complete, args=(serve_forever(),), daemon=True)
    thread.start()
    ready.wait(5)

    def push(event: Dict[str, Any]) -> None:
        asyncio.run_coroutine_threadsafe(fake.push(event), loop).result(5)

    try:
        received: List[Dict[str, Any]] = []
        with BitvavoWebSocket(url=fake.url, request_timeout=2.0) as ws:
            assert ws.get_time()["time"] > 0
            handle = ws.subscribe_trades("BTC-EUR", received.append)
            book = ws.watch_order_book("BTC-EUR")
            push({"event": "trade", "market": "BTC-EUR", "id": "t1"})
            push(
                {
                    "event": "book",
                    "market": "BTC-EUR",
                    "nonce": 2,
                    "bids": [["5.5", "1"]],
                    "asks": [],
                }
            )
            deadline = time.monotonic() + 5
            while (not received or book.nonce != 2) and time.monotonic() < deadline:
                time.sleep(0.01)
            assert received[0]["id"] == "t1"
            assert book.best_bid == (Decimal("5.5"), Decimal(1))
            handle.unsubscribe()
        assert not ws.connected
    finally:
        loop.call_soon_threadsafe(stop["event"].set)
        thread.join(5)


def test_sync_client_rejects_blocking_call_from_callback():
    fake = FakeBitvavo()
    errors: List[BaseException] = []
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    stop: Dict[str, Any] = {}

    async def serve_forever() -> None:
        async with serve(fake.handler, "127.0.0.1", 0) as server:
            fake.url = f"ws://127.0.0.1:{next(iter(server.sockets)).getsockname()[1]}/v2/"
            stop["event"] = asyncio.Event()
            ready.set()
            await stop["event"].wait()

    thread = threading.Thread(target=loop.run_until_complete, args=(serve_forever(),), daemon=True)
    thread.start()
    ready.wait(5)
    try:
        with BitvavoWebSocket(url=fake.url, request_timeout=2.0) as ws:

            def callback(event: Dict[str, Any]) -> None:
                try:
                    ws.get_time()  # would deadlock the event loop
                except RuntimeError as exc:
                    errors.append(exc)

            ws.subscribe_trades("BTC-EUR", callback)
            asyncio.run_coroutine_threadsafe(
                fake.push({"event": "trade", "market": "BTC-EUR"}), loop
            ).result(5)
            deadline = time.monotonic() + 5
            while not errors and time.monotonic() < deadline:
                time.sleep(0.01)
        assert errors and "callback" in str(errors[0])
    finally:
        loop.call_soon_threadsafe(stop["event"].set)
        thread.join(5)
