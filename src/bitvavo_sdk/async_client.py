"""Asyncio client."""

from __future__ import annotations

import asyncio
import time
from types import TracebackType
from typing import Any, Dict, Optional, Type

import httpx

from ._async_endpoints import AsyncEndpoints
from ._base import _CLOCK_SKEW_CODE, logger
from .errors import APIError, TransportError


class AsyncBitvavo(AsyncEndpoints):
    """Asyncio client for the Bitvavo REST API. Same methods as
    :class:`~bitvavo_sdk.Bitvavo`, but every endpoint is ``async``.

    Example:
        >>> async with AsyncBitvavo() as client:
        ...     book, ticker = await asyncio.gather(
        ...         client.get_order_book("BTC-EUR", depth=5),
        ...         client.get_ticker_price("BTC-EUR"),
        ...     )

    Pass ``http_client`` to reuse a configured :class:`httpx.AsyncClient`.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        *,
        http_client: Optional[httpx.AsyncClient] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(api_key, api_secret, **kwargs)
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=self.timeout)

    async def close(self) -> None:
        """Close the connection pool (only if this client created it)."""
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> AsyncBitvavo:
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        await self.close()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
        private: bool = False,
        weight: int = 1,
    ) -> Any:
        """Call any endpoint directly. See :meth:`bitvavo_sdk.Bitvavo.request`."""
        return await self._call(
            method, path, params=params, body=body, private=private, weight=weight
        )

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
        method = method.upper()
        attempt = 0
        resynced_clock = False
        while True:
            wait = self._rate_limit_wait(weight)
            if wait:
                await asyncio.sleep(wait)
                self._after_rate_limit_wait()
            req = self._prepare(method, path, params, body, private, weight)
            self.rate_limit.consume(weight)
            started = time.monotonic()
            try:
                response = await self._http.request(
                    req.method, req.url, headers=req.headers, content=req.content
                )
            except httpx.HTTPError as exc:
                self._log(req, type(exc).__name__, started)
                if method == "GET" and attempt < self.max_retries:
                    attempt += 1
                    await asyncio.sleep(self._backoff(attempt))
                    continue
                raise TransportError(f"{method} {path} failed: {exc!r}") from exc
            self._log(req, response.status_code, started)
            try:
                return self._handle(response)
            except APIError as err:
                if err.error_code == _CLOCK_SKEW_CODE and not resynced_clock:
                    resynced_clock = True
                    logger.warning("request outside access window; re-syncing clock")
                    await self.sync_time()
                    continue
                if self._should_retry_error(method, err) and attempt < self.max_retries:
                    attempt += 1
                    await asyncio.sleep(self._backoff(attempt))
                    continue
                raise
