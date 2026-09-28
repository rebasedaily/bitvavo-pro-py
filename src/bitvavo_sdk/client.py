"""Synchronous client."""

from __future__ import annotations

import time
from types import TracebackType
from typing import Any, Dict, Optional, Type

import httpx

from ._base import _CLOCK_SKEW_CODE, logger
from ._endpoints import SyncEndpoints
from .errors import APIError, TransportError


class Bitvavo(SyncEndpoints):
    """Blocking client for the Bitvavo REST API.

    Example:
        >>> from bitvavo_sdk import Bitvavo
        >>> with Bitvavo() as client:          # public endpoints need no key
        ...     client.get_ticker_price("BTC-EUR")["price"]

    Every endpoint is a method; see :class:`~bitvavo_sdk._endpoints.SyncEndpoints`
    for the full list. Constructor arguments are documented on
    :class:`~bitvavo_sdk._base.BaseClient`; additionally ``http_client`` lets you pass
    a pre-configured :class:`httpx.Client` (proxies, custom TLS, HTTP/2...).
    The client is thread-safe as long as the underlying ``httpx.Client`` is.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        *,
        http_client: Optional[httpx.Client] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(api_key, api_secret, **kwargs)
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(timeout=self.timeout)

    def close(self) -> None:
        """Close the connection pool (only if this client created it)."""
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> Bitvavo:
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
        private: bool = False,
        weight: int = 1,
    ) -> Any:
        """Call any endpoint directly, e.g. one this SDK does not wrap yet.

        ``path`` is relative to ``base_url`` (``"/markets"``). Signing, retries,
        rate limiting and error mapping apply as for the typed methods.
        """
        return self._call(method, path, params=params, body=body, private=private, weight=weight)

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
        method = method.upper()
        attempt = 0
        resynced_clock = False
        while True:
            wait = self._rate_limit_wait(weight)
            if wait:
                time.sleep(wait)
                self._after_rate_limit_wait()
            req = self._prepare(method, path, params, body, private, weight)
            self.rate_limit.consume(weight)
            started = time.monotonic()
            try:
                response = self._http.request(
                    req.method, req.url, headers=req.headers, content=req.content
                )
            except httpx.HTTPError as exc:
                self._log(req, type(exc).__name__, started)
                if method == "GET" and attempt < self.max_retries:
                    attempt += 1
                    time.sleep(self._backoff(attempt))
                    continue
                raise TransportError(f"{method} {path} failed: {exc!r}") from exc
            self._log(req, response.status_code, started)
            try:
                return self._handle(response)
            except APIError as err:
                if err.error_code == _CLOCK_SKEW_CODE and not resynced_clock:
                    resynced_clock = True
                    logger.warning("request outside access window; re-syncing clock")
                    self.sync_time()
                    continue
                if self._should_retry_error(method, err) and attempt < self.max_retries:
                    attempt += 1
                    time.sleep(self._backoff(attempt))
                    continue
                raise
