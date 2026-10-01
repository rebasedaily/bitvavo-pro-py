"""A local copy of a Bitvavo order book, kept in sync from WebSocket ``book`` events.

Bitvavo streams the book as deltas: each event lists changed price levels (size
``"0"`` removes a level) and carries a ``nonce`` that increases by exactly 1 per
change. A correct local book therefore needs a snapshot plus every delta after it,
in order. :class:`LocalOrderBook` holds the state; the WebSocket clients feed it and
resynchronise from a fresh snapshot whenever a nonce gap (or a reconnect) shows an
update was missed.
"""

from __future__ import annotations

import threading
import time
from decimal import Decimal
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

Level = Tuple[Decimal, Decimal]  # (price, size)


class LocalOrderBook:
    """Thread-safe local order book for one market.

    Prices and sizes are :class:`~decimal.Decimal`. Read methods can be called from
    any thread. Created by ``watch_order_book()`` on a WebSocket client.
    """

    def __init__(self, market: str) -> None:
        self.market = market
        self._bids: Dict[Decimal, Decimal] = {}
        self._asks: Dict[Decimal, Decimal] = {}
        self._lock = threading.Lock()
        self._listeners: List[Callable[[LocalOrderBook], Any]] = []
        #: Nonce of the last applied update; ``None`` until the first snapshot.
        self.nonce: Optional[int] = None
        #: ``time.time()`` of the last snapshot or update.
        self.updated_at: Optional[float] = None
        #: How many times the book was rebuilt from a snapshot (1 = never resynced).
        self.snapshots = 0
        self._synced = False

    # -- reading --------------------------------------------------------------------

    @property
    def is_synced(self) -> bool:
        """``False`` while (re)loading a snapshot, e.g. after a gap or reconnect."""
        return self._synced

    def bids(self, depth: Optional[int] = None) -> List[Level]:
        """Bid levels, best (highest) first."""
        with self._lock:
            levels = sorted(self._bids.items(), key=lambda kv: kv[0], reverse=True)
        return levels[:depth] if depth is not None else levels

    def asks(self, depth: Optional[int] = None) -> List[Level]:
        """Ask levels, best (lowest) first."""
        with self._lock:
            levels = sorted(self._asks.items(), key=lambda kv: kv[0])
        return levels[:depth] if depth is not None else levels

    @property
    def best_bid(self) -> Optional[Level]:
        with self._lock:
            if not self._bids:
                return None
            price = max(self._bids)
            return price, self._bids[price]

    @property
    def best_ask(self) -> Optional[Level]:
        with self._lock:
            if not self._asks:
                return None
            price = min(self._asks)
            return price, self._asks[price]

    @property
    def spread(self) -> Optional[Decimal]:
        bid, ask = self.best_bid, self.best_ask
        return ask[0] - bid[0] if bid and ask else None

    @property
    def mid_price(self) -> Optional[Decimal]:
        bid, ask = self.best_bid, self.best_ask
        return (ask[0] + bid[0]) / 2 if bid and ask else None

    def add_listener(self, callback: Callable[[LocalOrderBook], Any]) -> None:
        """Call ``callback(book)`` after every applied update or snapshot.

        Runs on the WebSocket's event-loop thread: keep it fast and non-blocking.
        """
        self._listeners.append(callback)

    def __repr__(self) -> str:
        return (
            f"LocalOrderBook({self.market!r}, best_bid={self.best_bid}, "
            f"best_ask={self.best_ask}, nonce={self.nonce}, synced={self._synced})"
        )

    # -- feeding (used by the WebSocket clients) --------------------------------------

    def _mark_unsynced(self) -> None:
        self._synced = False

    def _load_snapshot(self, snapshot: Mapping[str, Any]) -> None:
        bids = _levels(snapshot.get("bids", ()))
        asks = _levels(snapshot.get("asks", ()))
        with self._lock:
            self._bids, self._asks = bids, asks
            self.nonce = int(snapshot["nonce"])
            self.updated_at = time.time()
            self.snapshots += 1
            self._synced = True
        self._notify()

    def _apply(self, event: Mapping[str, Any]) -> Optional[bool]:
        """Apply one ``book`` event.

        Returns ``True`` if applied, ``None`` if it was older than the book (ignored),
        ``False`` on a nonce gap: the caller must resync from a snapshot.
        """
        nonce = int(event["nonce"])
        with self._lock:
            if self.nonce is None or nonce <= self.nonce:
                return None
            if nonce != self.nonce + 1:
                self._synced = False
                return False
            _update(self._bids, event.get("bids", ()))
            _update(self._asks, event.get("asks", ()))
            self.nonce = nonce
            self.updated_at = time.time()
            self._synced = True  # contiguous with the last applied state
        self._notify()
        return True

    def _notify(self) -> None:
        for callback in list(self._listeners):
            callback(self)


def _levels(rows: Sequence[Sequence[str]]) -> Dict[Decimal, Decimal]:
    out: Dict[Decimal, Decimal] = {}
    for price, size, *_ in rows:
        amount = Decimal(size)
        if amount:
            out[Decimal(price)] = amount
    return out


def _update(side: Dict[Decimal, Decimal], rows: Sequence[Sequence[str]]) -> None:
    for price, size, *_ in rows:
        # Decimal keys: "74133.00" from an update and "74133" from a snapshot are the
        # same level (equal Decimals hash equally); string keys would split them.
        p, amount = Decimal(price), Decimal(size)
        if amount:
            side[p] = amount
        else:
            side.pop(p, None)
