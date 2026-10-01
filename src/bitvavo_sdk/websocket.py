"""Asyncio client for the Bitvavo WebSocket API.

One connection gives you:

* every typed endpoint method of the REST clients (``get_markets``, ``create_order``,
  ``market_buy``, ``find_order`` ...), sent as WebSocket actions;
* streaming subscriptions (ticker, 24h ticker, book, trades, candles, and your own
  orders and fills) as async iterators;
* a self-healing local order book (:meth:`AsyncBitvavoWebSocket.watch_order_book`);
* automatic reconnection that re-authenticates and restores every subscription.

See https://docs.bitvavo.com/docs/websocket-api/introduction/.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import itertools
import json
import logging
from collections import defaultdict
from types import TracebackType
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Tuple,
    Type,
    Union,
)
from urllib.parse import urlsplit

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from ._async_endpoints import AsyncEndpoints
from ._ws_routes import route
from .auth import create_signature
from .errors import (
    AuthenticationError,
    BitvavoError,
    MissingCredentialsError,
    TransportError,
    error_from_payload,
)
from .orderbook import LocalOrderBook

logger = logging.getLogger("bitvavo_sdk.websocket")

DEFAULT_WS_URL = "wss://ws.bitvavo.com/v2/"

#: Subscription key: (channel, market or "*", candle interval or None)
_Key = Tuple[str, str, Optional[str]]
Markets = Union[str, Sequence[str]]

_CLOSED = object()  # queue sentinel: the subscription has ended


class Subscription:
    """Events from one ``subscribe`` call, consumed as an async iterator.

    >>> async with await ws.subscribe_ticker(["BTC-EUR"]) as sub:
    ...     async for event in sub:
    ...         print(event["market"], event.get("bestBid"))

    Events are buffered in a bounded queue. When a slow consumer lets it fill up the
    oldest events are dropped and counted in :attr:`dropped`.
    """

    def __init__(
        self,
        client: AsyncBitvavoWebSocket,
        channel: str,
        markets: Sequence[str],
        intervals: Sequence[Optional[str]],
        maxsize: int,
    ) -> None:
        self.channel = channel
        self.markets = tuple(markets)
        self.intervals = tuple(intervals)
        self.dropped = 0
        self._client = client
        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize)
        self._closed = False

    @property
    def keys(self) -> List[_Key]:
        return [(self.channel, m, i) for m in self.markets for i in self.intervals]

    @property
    def closed(self) -> bool:
        return self._closed

    def _put(self, event: Any) -> None:
        if self._closed:
            return
        if self._queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
            self.dropped += 1
            if self.dropped in (1, 100) or self.dropped % 10_000 == 0:
                logger.warning(
                    "%s subscription queue full: %d events dropped", self.channel, self.dropped
                )
        self._queue.put_nowait(event)

    def _close(self) -> None:
        if not self._closed:
            self._closed = True
            if self._queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    self._queue.get_nowait()
            self._queue.put_nowait(_CLOSED)

    async def get(self, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Next event. Raises :class:`StopAsyncIteration` once unsubscribed/closed and
        :class:`asyncio.TimeoutError` if ``timeout`` passes first."""
        item = await asyncio.wait_for(self._queue.get(), timeout)
        if item is _CLOSED:
            self._queue.put_nowait(_CLOSED)  # keep later get() calls terminating too
            raise StopAsyncIteration
        return item  # type: ignore[no-any-return]

    def __aiter__(self) -> AsyncIterator[Dict[str, Any]]:
        return self

    async def __anext__(self) -> Dict[str, Any]:
        return await self.get()

    async def unsubscribe(self) -> None:
        """Stop this subscription. Safe to call more than once."""
        await self._client._unsubscribe(self)

    async def __aenter__(self) -> Subscription:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.unsubscribe()

    def __repr__(self) -> str:
        return f"Subscription({self.channel!r}, markets={list(self.markets)})"


class AsyncBitvavoWebSocket(AsyncEndpoints):
    """Asyncio WebSocket client.

    Example:
        >>> async with AsyncBitvavoWebSocket.from_env() as ws:
        ...     print(await ws.get_ticker_price("BTC-EUR"))           # request/response
        ...     async for trade in await ws.subscribe_trades(["BTC-EUR"]):
        ...         print(trade["price"], trade["amount"])

    Args:
        api_key, api_secret: Needed for private actions and the ``account`` channel.
            The connection authenticates on connect and after every reconnect.
        operator_id: Default ``operatorId`` for order actions.
        url: WebSocket endpoint.
        request_timeout: Seconds to wait for the response to an action. A timeout on
            an order action means the outcome is unknown: use :meth:`find_order`.
        access_window_ms: Validity window of the authentication message.
        reconnect: Reconnect automatically when the connection drops.
        max_reconnect_delay: Upper bound of the exponential reconnect backoff.
        ping_interval: Seconds between WebSocket keep-alive pings.
        queue_size: Buffer per subscription before old events are dropped.
        on_reconnect: Called (sync or async) after a reconnect has restored
            authentication and subscriptions. Events that happened while
            disconnected were missed: use it to re-read orders or balances.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        *,
        operator_id: Optional[int] = None,
        url: str = DEFAULT_WS_URL,
        request_timeout: float = 10.0,
        access_window_ms: int = 10_000,
        reconnect: bool = True,
        max_reconnect_delay: float = 30.0,
        ping_interval: Optional[float] = 20.0,
        queue_size: int = 10_000,
        on_reconnect: Optional[Callable[[], Any]] = None,
    ) -> None:
        super().__init__(
            api_key,
            api_secret,
            operator_id=operator_id,
            timeout=request_timeout,
            access_window_ms=access_window_ms,
        )
        self.url = url
        self.reconnect = reconnect
        self.max_reconnect_delay = max_reconnect_delay
        self.ping_interval = ping_interval
        self.queue_size = queue_size
        self.on_reconnect = on_reconnect
        #: Number of successful reconnects since :meth:`connect`.
        self.reconnects = 0
        self.authenticated = False
        self._sign_path = urlsplit(url).path.rstrip("/") + "/websocket"
        self._ws: Optional[ClientConnection] = None
        self._run_task: Optional[asyncio.Task[None]] = None
        self._restore_task: Optional[asyncio.Task[None]] = None
        self._ready: Optional[asyncio.Event] = None
        self._pending: Dict[int, asyncio.Future[Any]] = {}
        self._ids = itertools.count(1)
        self._subs: Dict[_Key, List[Subscription]] = defaultdict(list)
        self._sub_lock: Optional[asyncio.Lock] = None
        self._books: List[Tuple[LocalOrderBook, asyncio.Task[None]]] = []
        self._closing = False

    def __repr__(self) -> str:
        key = f"{self._api_key[:4]}..." if self._api_key else None
        return f"{type(self).__name__}(api_key={key!r}, url={self.url!r})"

    # ------------------------------------------------------------------ lifecycle

    @property
    def connected(self) -> bool:
        return self._ready is not None and self._ready.is_set()

    async def connect(self) -> None:
        """Open the connection (and authenticate if credentials were given).

        Called automatically by the first request or subscription.
        """
        if self._run_task is not None and not self._run_task.done():
            return
        self._closing = False
        self._ready = asyncio.Event()
        self._sub_lock = asyncio.Lock()
        await self._open_socket()
        self._run_task = asyncio.create_task(self._run(), name="bitvavo-ws-reader")
        try:
            await self._authenticate()
        except BaseException:
            await self.close()
            raise
        self._ready.set()

    async def close(self) -> None:
        """Close the connection and end every subscription and watched book."""
        self._closing = True
        if self._restore_task is not None:
            self._restore_task.cancel()
        books, self._books = self._books, []
        for _, task in books:
            task.cancel()
        for _, task in books:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if self._ws is not None:
            await self._ws.close()
        if self._run_task is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._run_task
        self._run_task = None
        self._fail_pending(TransportError("WebSocket closed"))
        for subs in list(self._subs.values()):
            for sub in subs:
                sub._close()
        self._subs.clear()

    async def __aenter__(self) -> AsyncBitvavoWebSocket:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        await self.close()

    async def _open_socket(self) -> None:
        try:
            self._ws = await connect(
                self.url,
                ping_interval=self.ping_interval,
                ping_timeout=self.ping_interval,
                open_timeout=self.timeout,
                max_size=2**24,
            )
        except (OSError, WebSocketException, asyncio.TimeoutError) as exc:
            raise TransportError(f"cannot connect to {self.url}: {exc!r}") from exc
        logger.debug("connected to %s", self.url)

    async def _run(self) -> None:
        """Reader loop: dispatch messages; on disconnect, reconnect and restore."""
        while True:
            ws = self._ws
            assert ws is not None
            try:
                async for raw in ws:
                    self._dispatch(raw)
            except ConnectionClosed:
                pass
            except Exception:  # never let a bad message kill the reader
                logger.exception("WebSocket reader failed")
            if self._ready is not None:
                self._ready.clear()
            self.authenticated = False
            self._fail_pending(TransportError("WebSocket connection lost"))
            for book, _ in self._books:
                book._mark_unsynced()
            if self._closing or not self.reconnect:
                for subs in list(self._subs.values()):
                    for sub in subs:
                        sub._close()
                return
            await self._reconnect_socket()
            self._restore_task = asyncio.create_task(self._restore(), name="bitvavo-ws-restore")

    async def _reconnect_socket(self) -> None:
        delay = 0.5
        while not self._closing:
            logger.warning("WebSocket disconnected; reconnecting in %.1fs", delay)
            await asyncio.sleep(delay)
            try:
                await self._open_socket()
                return
            except TransportError as exc:
                logger.warning("reconnect failed: %s", exc)
                delay = min(delay * 2, self.max_reconnect_delay)

    async def _restore(self) -> None:
        """After a reconnect: re-authenticate, resubscribe, then notify."""
        try:
            await self._authenticate()
            keys = list(self._subs)
            if keys:
                await self._send_subscription("subscribe", keys, wait_ready=False)
        except BitvavoError as exc:
            logger.error("restoring WebSocket session failed: %s; retrying", exc)
            if self._ws is not None:
                await self._ws.close()  # the reader loop reconnects and retries
            return
        assert self._ready is not None
        self._ready.set()
        self.reconnects += 1
        logger.info("WebSocket reconnected; %d subscriptions restored", len(self._subs))
        if self.on_reconnect is not None:
            result = self.on_reconnect()
            if inspect.isawaitable(result):
                await result

    # ------------------------------------------------------------- authentication

    async def _authenticate(self) -> None:
        if self._api_key is None or self._api_secret is None:
            return
        for attempt in range(2):
            timestamp = self._now_ms()
            payload = {
                "action": "authenticate",
                "key": self._api_key,
                "signature": create_signature(self._api_secret, timestamp, "GET", self._sign_path),
                "timestamp": timestamp,
                "window": self.access_window_ms,
            }
            try:
                ok = await self._request(payload, wait_ready=False)
            except AuthenticationError as exc:
                if exc.error_code == 304 and attempt == 0:
                    await self._sync_time_internal()
                    continue
                raise
            if ok is not True:
                raise AuthenticationError(
                    "authentication was not confirmed", status_code=403, error_code=None
                )
            self.authenticated = True
            return

    async def _sync_time_internal(self) -> None:
        loop = asyncio.get_running_loop()
        started = loop.time()
        server = await self._request({"action": "getTime"}, wait_ready=False)
        elapsed_ms = (loop.time() - started) * 1000
        self.time_offset_ms = 0
        self.time_offset_ms = int(server["time"] - (self._now_ms() - elapsed_ms / 2))

    # ------------------------------------------------------------ request/response

    async def _call(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
        private: bool = False,
        weight: int = 1,
    ) -> Any:
        action, market = route(method.upper(), path)
        if private and not self.has_credentials:
            raise MissingCredentialsError(f"{action} requires api_key and api_secret")
        payload: Dict[str, Any] = {"action": action}
        if market is not None:
            payload["market"] = market
        for source in (params, body):
            if source:
                payload.update({k: v for k, v in source.items() if v is not None})
        return await self._request(payload)

    async def request_action(self, action: str, **params: Any) -> Any:
        """Send any WebSocket action directly, e.g. one this SDK does not wrap yet.

        >>> await ws.request_action("getBook", market="BTC-EUR", depth=5)
        """
        payload = {"action": action, **{k: v for k, v in params.items() if v is not None}}
        return await self._request(payload)

    async def _request(self, payload: Dict[str, Any], *, wait_ready: bool = True) -> Any:
        if self._run_task is None or self._run_task.done():
            await self.connect()
        assert self._ready is not None
        if wait_ready and not self._ready.is_set():
            try:
                await asyncio.wait_for(self._ready.wait(), self.timeout)
            except asyncio.TimeoutError:
                raise TransportError("WebSocket is not connected (reconnecting)") from None
        request_id = next(self._ids)
        message = dict(payload, requestId=request_id)
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        future.add_done_callback(_consume_exception)
        self._pending[request_id] = future
        action = payload.get("action")
        try:
            ws = self._ws
            if ws is None:
                raise TransportError("WebSocket is not connected")
            await ws.send(json.dumps(message, separators=(",", ":")))
            return await asyncio.wait_for(future, self.timeout)
        except asyncio.TimeoutError:
            raise TransportError(
                f"no response to {action} within {self.timeout}s (outcome unknown)"
            ) from None
        except ConnectionClosed as exc:
            raise TransportError(f"connection lost while sending {action}") from exc
        finally:
            self._pending.pop(request_id, None)

    def _fail_pending(self, error: BaseException) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._pending.clear()

    # ------------------------------------------------------------------ dispatch

    def _dispatch(self, raw: Union[str, bytes]) -> None:
        try:
            msg = json.loads(raw)
        except ValueError:
            logger.warning("ignoring non-JSON message: %.200r", raw)
            return
        if not isinstance(msg, dict):
            return
        request_id = msg.get("requestId")
        if request_id is not None and request_id in self._pending:
            future = self._pending[request_id]
            if not future.done():
                if "errorCode" in msg:
                    future.set_exception(error_from_payload(msg))
                elif msg.get("event") == "authenticate":
                    future.set_result(msg.get("authenticated"))
                elif msg.get("event") in ("subscribed", "unsubscribed"):
                    future.set_result(msg.get("subscriptions"))
                else:
                    future.set_result(msg.get("response"))
            return
        if "errorCode" in msg:
            logger.warning("unsolicited WebSocket error: %s", msg)
            return
        self._route_event(msg)

    def _route_event(self, msg: Dict[str, Any]) -> None:
        event = msg.get("event")
        if event == "ticker24h":
            data = msg.get("data")
            # Documented as an object; the live API sends a list of objects.
            items = data if isinstance(data, list) else [data] if data else []
            for item in items:
                self._deliver(("ticker24h", item.get("market"), None), dict(item, event=event))
        elif event in ("ticker", "book"):
            self._deliver((event, msg.get("market"), None), msg)
        elif event == "trade":
            self._deliver(("trades", msg.get("market"), None), msg)
        elif event in ("candle", "candles"):  # docs say "candles", live API sends "candle"
            self._deliver(("candles", msg.get("market"), msg.get("interval")), msg)
        elif event in ("order", "fill"):
            self._deliver(("account", msg.get("market"), None), msg)
            self._deliver(("account", "*", None), msg)

    def _deliver(self, key: Tuple[str, Any, Optional[str]], event: Dict[str, Any]) -> None:
        for sub in self._subs.get(key, ()):
            sub._put(event)

    # -------------------------------------------------------------- subscriptions

    async def subscribe(
        self,
        channel: str,
        markets: Markets,
        *,
        intervals: Optional[Sequence[str]] = None,
    ) -> Subscription:
        """Subscribe to a channel and return a :class:`Subscription`.

        Args:
            channel: ``ticker``, ``ticker24h``, ``book``, ``trades``, ``candles`` or
                ``account`` (private).
            markets: Market names, or ``"*"`` for every market (``account`` only).
            intervals: Candle intervals, required for ``candles``.
        """
        if channel == "account" and not self.has_credentials:
            raise MissingCredentialsError("the account channel requires api_key and api_secret")
        if channel == "candles" and not intervals:
            raise ValueError("candles subscriptions need intervals, e.g. ['1m']")
        market_list = (
            ["*"] if markets == "*" else [markets] if isinstance(markets, str) else list(markets)
        )
        if not market_list:
            raise ValueError("pass at least one market")
        if self._run_task is None or self._run_task.done():
            await self.connect()
        assert self._sub_lock is not None
        sub = Subscription(
            self, channel, market_list, list(intervals) if intervals else [None], self.queue_size
        )
        async with self._sub_lock:
            new_keys = [k for k in sub.keys if not self._subs.get(k)]
            for key in sub.keys:  # register first so no early event is missed
                self._subs[key].append(sub)
            if new_keys:
                try:
                    await self._send_subscription("subscribe", new_keys)
                except BaseException:
                    self._remove(sub)
                    raise
        return sub

    async def _unsubscribe(self, sub: Subscription) -> None:
        if sub.closed:
            return
        sub._close()
        if self._sub_lock is None:
            return
        async with self._sub_lock:
            orphaned = self._remove(sub)
            if orphaned and self.connected and not self._closing:
                try:
                    await self._send_subscription("unsubscribe", orphaned)
                except BitvavoError as exc:
                    logger.warning("unsubscribe failed: %s", exc)

    def _remove(self, sub: Subscription) -> List[_Key]:
        orphaned = []
        for key in sub.keys:
            subs = self._subs.get(key)
            if subs and sub in subs:
                subs.remove(sub)
                if not subs:
                    del self._subs[key]
                    orphaned.append(key)
        return orphaned

    async def _send_subscription(
        self, action: str, keys: Iterable[_Key], *, wait_ready: bool = True
    ) -> None:
        grouped: Dict[Tuple[str, Optional[str]], List[str]] = defaultdict(list)
        for channel, market, interval in keys:
            grouped[(channel, interval)].append(market)
        channels: List[Dict[str, Any]] = []
        for (channel, interval), markets in grouped.items():
            entry: Dict[str, Any] = {
                "name": channel,
                "markets": "*" if markets == ["*"] else markets,
            }
            if interval is not None:
                entry["interval"] = [interval]
            channels.append(entry)
        await self._request({"action": action, "channels": channels}, wait_ready=wait_ready)

    async def subscribe_ticker(self, markets: Markets) -> Subscription:
        """Best bid/ask changes. Events carry **only the fields that changed**."""
        return await self.subscribe("ticker", markets)

    async def subscribe_ticker24h(self, markets: Markets) -> Subscription:
        """24h statistics, about once per second per market."""
        return await self.subscribe("ticker24h", markets)

    async def subscribe_book(self, markets: Markets) -> Subscription:
        """Raw order book deltas. Most users want :meth:`watch_order_book` instead."""
        return await self.subscribe("book", markets)

    async def subscribe_trades(self, markets: Markets) -> Subscription:
        """Every public trade."""
        return await self.subscribe("trades", markets)

    async def subscribe_candles(self, markets: Markets, intervals: Sequence[str]) -> Subscription:
        """Candle updates, ``candle`` is ``[[timestamp, open, high, low, close, volume]]``."""
        return await self.subscribe("candles", markets, intervals=intervals)

    async def subscribe_account(self, markets: Markets = "*") -> Subscription:
        """Your ``order`` and ``fill`` events. Requires authentication."""
        return await self.subscribe("account", markets)

    # ----------------------------------------------------------------- order book

    async def watch_order_book(
        self,
        market: str,
        *,
        depth: int = 1000,
        on_update: Optional[Callable[[LocalOrderBook], Any]] = None,
    ) -> LocalOrderBook:
        """Maintain a local order book for ``market`` until :meth:`close`.

        Subscribes to ``book`` deltas, loads a snapshot of ``depth`` levels, applies
        updates in nonce order and reloads the snapshot whenever a gap or reconnect
        means an update was missed. Returns once the first snapshot is loaded.
        """
        book = LocalOrderBook(market)
        if on_update is not None:
            book.add_listener(on_update)
        sub = await self.subscribe_book([market])
        loaded = asyncio.get_running_loop().create_future()
        task = asyncio.create_task(self._maintain_book(book, sub, depth, loaded))
        self._books.append((book, task))
        try:
            await loaded
        except BaseException:
            task.cancel()
            raise
        return book

    async def stop_watching(self, book: LocalOrderBook) -> None:
        """Stop maintaining ``book`` and drop its subscription."""
        for entry in list(self._books):
            if entry[0] is book:
                self._books.remove(entry)
                entry[1].cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await entry[1]

    async def _maintain_book(
        self,
        book: LocalOrderBook,
        sub: Subscription,
        depth: int,
        loaded: asyncio.Future[None],
    ) -> None:
        try:
            while True:
                try:
                    snapshot = await self.get_order_book(book.market, depth=depth)
                except BitvavoError as exc:
                    if not loaded.done():
                        loaded.set_exception(exc)
                        return
                    logger.warning("book snapshot for %s failed: %s", book.market, exc)
                    await asyncio.sleep(1)
                    continue
                book._load_snapshot(snapshot)
                if not loaded.done():
                    loaded.set_result(None)
                async for event in sub:
                    if book._apply(event) is False:
                        logger.info("%s book: nonce gap, resyncing", book.market)
                        break
                else:
                    return  # subscription closed
        finally:
            book._mark_unsynced()
            await sub.unsubscribe()


def _consume_exception(future: asyncio.Future[Any]) -> None:
    if not future.cancelled():
        future.exception()
