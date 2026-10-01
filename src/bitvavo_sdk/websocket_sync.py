"""Blocking WebSocket client: runs :class:`AsyncBitvavoWebSocket` on a background thread."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from types import TracebackType
from typing import Any, Callable, Coroutine, Dict, Optional, Sequence, Type, TypeVar

from ._endpoints import SyncEndpoints
from .errors import TransportError
from .orderbook import LocalOrderBook
from .websocket import AsyncBitvavoWebSocket, Markets, Subscription

logger = logging.getLogger("bitvavo_sdk.websocket")

T = TypeVar("T")
Callback = Callable[[Dict[str, Any]], Any]


class SyncSubscription:
    """Handle for a callback subscription created by :class:`BitvavoWebSocket`."""

    def __init__(
        self,
        client: BitvavoWebSocket,
        subscription: Subscription,
        pump: concurrent.futures.Future[None],
    ) -> None:
        self._client = client
        self.subscription = subscription
        self._pump = pump

    @property
    def dropped(self) -> int:
        """Events dropped because the callback could not keep up."""
        return self.subscription.dropped

    def unsubscribe(self) -> None:
        self._client._run(self.subscription.unsubscribe())

    def __enter__(self) -> SyncSubscription:
        return self

    def __exit__(self, *exc: object) -> None:
        self.unsubscribe()


class BitvavoWebSocket(SyncEndpoints):
    """Blocking WebSocket client with callback subscriptions.

    All typed endpoint methods (``get_markets``, ``create_order``, ...) are
    available and block until Bitvavo answers. Subscription callbacks and order
    book listeners run on the client's background thread: keep them short, and hand
    heavy work to your own queue or thread.

    Example:
        >>> with BitvavoWebSocket.from_env() as ws:
        ...     ws.subscribe_trades(["BTC-EUR"], lambda t: print(t["price"]))
        ...     book = ws.watch_order_book("BTC-EUR")
        ...     time.sleep(10)
        ...     print(book.best_bid, book.best_ask)

    Takes the same arguments as :class:`AsyncBitvavoWebSocket`.
    """

    def __init__(
        self, api_key: Optional[str] = None, api_secret: Optional[str] = None, **kwargs: Any
    ) -> None:
        super().__init__(
            api_key,
            api_secret,
            operator_id=kwargs.get("operator_id"),
            timeout=kwargs.get("request_timeout", 10.0),
            access_window_ms=kwargs.get("access_window_ms", 10_000),
        )
        self._kwargs = kwargs
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._client: Optional[AsyncBitvavoWebSocket] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ lifecycle

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.connected

    @property
    def reconnects(self) -> int:
        return self._client.reconnects if self._client else 0

    def connect(self) -> None:
        """Start the background thread and connect. Called by the first request."""
        with self._lock:
            if self._client is not None:
                return
            loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=loop.run_forever, name="bitvavo-websocket", daemon=True
            )
            thread.start()
            self._loop, self._thread = loop, thread
            client = self._run(self._create())
            try:
                self._run(client.connect())
            except BaseException:
                self._stop_loop()
                raise
            self._client = client

    async def _create(self) -> AsyncBitvavoWebSocket:
        client = AsyncBitvavoWebSocket(self._api_key, self._api_secret, **self._kwargs)
        client.time_offset_ms = self.time_offset_ms
        return client

    def close(self) -> None:
        """Close the connection and stop the background thread."""
        with self._lock:
            client, self._client = self._client, None
            if client is not None and self._loop is not None:
                try:
                    self._run(client.close(), timeout=10)
                except Exception:
                    logger.exception("error while closing WebSocket")
            self._stop_loop()

    def _stop_loop(self) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread is not None:
                self._thread.join(timeout=5)
            self._loop.close()
        self._loop = self._thread = None

    def __enter__(self) -> BitvavoWebSocket:
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self.close()

    def _run(self, coro: Coroutine[Any, Any, T], timeout: Optional[float] = None) -> T:
        if self._loop is None:
            coro.close()
            raise TransportError("WebSocket client is not connected; call connect()")
        if threading.current_thread() is self._thread:
            coro.close()
            raise RuntimeError(
                "blocking BitvavoWebSocket calls cannot be made from a subscription "
                "callback; hand the work to another thread"
            )
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        wait = timeout if timeout is not None else self.timeout * 3 + 5
        try:
            return future.result(wait)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise TransportError(f"no result within {wait}s") from None

    def _ensure(self) -> AsyncBitvavoWebSocket:
        if self._client is None:
            self.connect()
        assert self._client is not None
        return self._client

    # ------------------------------------------------------------ request/response

    def _call(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
        private: bool = False,
        weight: int = 1,
    ) -> Any:
        client = self._ensure()
        return self._run(
            client._call(method, path, params=params, body=body, private=private, weight=weight)
        )

    def sync_time(self) -> int:
        client = self._ensure()
        self.time_offset_ms = self._run(client.sync_time())
        return self.time_offset_ms

    def request_action(self, action: str, **params: Any) -> Any:
        """Send any WebSocket action directly."""
        return self._run(self._ensure().request_action(action, **params))

    # -------------------------------------------------------------- subscriptions

    def subscribe(
        self,
        channel: str,
        markets: Markets,
        callback: Callback,
        *,
        intervals: Optional[Sequence[str]] = None,
    ) -> SyncSubscription:
        """Subscribe and call ``callback(event)`` for every event (on the WS thread)."""
        client = self._ensure()
        sub = self._run(client.subscribe(channel, markets, intervals=intervals))
        assert self._loop is not None
        pump = asyncio.run_coroutine_threadsafe(_pump(sub, callback), self._loop)
        return SyncSubscription(self, sub, pump)

    def subscribe_ticker(self, markets: Markets, callback: Callback) -> SyncSubscription:
        """Best bid/ask changes; events carry only the fields that changed."""
        return self.subscribe("ticker", markets, callback)

    def subscribe_ticker24h(self, markets: Markets, callback: Callback) -> SyncSubscription:
        return self.subscribe("ticker24h", markets, callback)

    def subscribe_book(self, markets: Markets, callback: Callback) -> SyncSubscription:
        return self.subscribe("book", markets, callback)

    def subscribe_trades(self, markets: Markets, callback: Callback) -> SyncSubscription:
        return self.subscribe("trades", markets, callback)

    def subscribe_candles(
        self, markets: Markets, intervals: Sequence[str], callback: Callback
    ) -> SyncSubscription:
        return self.subscribe("candles", markets, callback, intervals=intervals)

    def subscribe_account(self, callback: Callback, markets: Markets = "*") -> SyncSubscription:
        """Your ``order`` and ``fill`` events. Requires authentication."""
        return self.subscribe("account", markets, callback)

    def watch_order_book(
        self,
        market: str,
        *,
        depth: int = 1000,
        on_update: Optional[Callable[[LocalOrderBook], Any]] = None,
    ) -> LocalOrderBook:
        """Maintain a local order book in the background; read it from any thread."""
        client = self._ensure()
        return self._run(client.watch_order_book(market, depth=depth, on_update=on_update))

    def stop_watching(self, book: LocalOrderBook) -> None:
        self._run(self._ensure().stop_watching(book))


async def _pump(sub: Subscription, callback: Callback) -> None:
    async for event in sub:
        try:
            callback(event)
        except Exception:
            logger.exception("subscription callback raised")
