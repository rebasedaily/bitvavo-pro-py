"""Tracking of Bitvavo's weight-based rate limit.

Bitvavo allows ``bitvavo-ratelimit-limit`` weight points per minute (1000 by
default). Exceeding it blocks an API key for one minute (an IP for 15 minutes when
unauthenticated). Every REST response reports the remaining budget in headers,
which :class:`RateLimitState` records.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Mapping, Optional


@dataclass
class RateLimitState:
    """Last-known rate limit budget, updated from every response."""

    limit: Optional[int] = None
    remaining: Optional[int] = None
    #: Unix time in milliseconds when ``remaining`` resets to ``limit``.
    reset_at: Optional[int] = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def update(self, headers: Mapping[str, str]) -> None:
        with self._lock:
            limit = _int(headers.get("bitvavo-ratelimit-limit"))
            remaining = _int(headers.get("bitvavo-ratelimit-remaining"))
            reset_at = _int(headers.get("bitvavo-ratelimit-resetat"))
            if limit is not None:
                self.limit = limit
            if remaining is not None:
                self.remaining = remaining
            if reset_at is not None:
                self.reset_at = reset_at

    def seconds_until_reset(self, now_ms: Optional[int] = None) -> float:
        if self.reset_at is None:
            return 0.0
        now_ms = int(time.time() * 1000) if now_ms is None else now_ms
        return max(0.0, (self.reset_at - now_ms) / 1000)

    def wait_needed(self, weight: int, buffer: int, now_ms: Optional[int] = None) -> float:
        """Seconds to wait before spending ``weight`` points without dipping under ``buffer``.

        Returns 0 when the budget is unknown, sufficient, or the window already reset.
        """
        with self._lock:
            if self.remaining is None or self.remaining - weight >= buffer:
                return 0.0
            return self.seconds_until_reset(now_ms)

    def consume(self, weight: int) -> None:
        """Optimistically spend points locally before the response confirms it."""
        with self._lock:
            if self.remaining is not None:
                self.remaining -= weight


def _int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None
