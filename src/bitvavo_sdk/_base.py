"""Transport-independent core shared by the sync and async clients."""

from __future__ import annotations

import json
import logging
import os
import platform
import time
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Type, TypeVar
from urllib.parse import urlencode, urlsplit

import httpx

from ._version import __version__
from .auth import auth_headers
from .errors import APIError, MissingCredentialsError, error_from_response
from .rate_limit import RateLimitState
from .types import Number
from .utils import format_number

logger = logging.getLogger("bitvavo_sdk")

DEFAULT_BASE_URL = "https://api.bitvavo.com/v2"
DEFAULT_TIMEOUT = 10.0
DEFAULT_ACCESS_WINDOW_MS = 10_000

# errorCodes documented as "request was not processed, retry shortly". Safe to retry
# even for order-changing requests. errorCode 109 (timeout) is deliberately absent:
# its outcome is unknown.
_SAFE_RETRY_CODES = frozenset({107, 111})
# errorCode 304: request arrived outside the access window, i.e. our clock drifted.
_CLOCK_SKEW_CODE = 304

_C = TypeVar("_C", bound="BaseClient")


@dataclass(frozen=True)
class PreparedRequest:
    method: str
    url: str
    headers: Dict[str, str]
    content: Optional[str]
    weight: int


class BaseClient:
    """Configuration, signing and response handling shared by both clients."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        *,
        operator_id: Optional[int] = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        access_window_ms: int = DEFAULT_ACCESS_WINDOW_MS,
        max_retries: int = 2,
        retry_backoff: float = 0.5,
        rate_limit_buffer: int = 20,
        wait_on_rate_limit: bool = True,
        user_agent: Optional[str] = None,
    ) -> None:
        """
        Args:
            api_key: Bitvavo API key. Optional for public endpoints; when given, public
                requests are signed too, which grants the per-account rate limit.
            api_secret: Bitvavo API secret.
            operator_id: Default ``operatorId`` sent with order requests. Bitvavo
                requires it on every create/update/cancel call; it identifies the
                trader or bot within your account.
            base_url: API root including the version path.
            timeout: Per-request timeout in seconds.
            access_window_ms: ``Bitvavo-Access-Window`` (100-60000 ms).
            max_retries: Retries for transient failures. GET requests are retried on
                network errors and 5xx; other methods only on errorCodes 107/111,
                which Bitvavo documents as "not processed".
            retry_backoff: Base delay in seconds, doubled per attempt.
            rate_limit_buffer: Keep at least this many weight points in reserve.
            wait_on_rate_limit: Sleep until the window resets instead of spending the
                reserve. Disable for latency-critical paths that manage their own budget.
            user_agent: Override the ``User-Agent`` header.
        """
        if (api_key is None) != (api_secret is None):
            raise ValueError("api_key and api_secret must be given together")
        if not 100 <= access_window_ms <= 60_000:
            raise ValueError("access_window_ms must be between 100 and 60000")
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        self._api_key = api_key
        self._api_secret = api_secret
        self.operator_id = operator_id
        self.base_url = base_url.rstrip("/")
        self._sign_prefix = urlsplit(self.base_url).path.rstrip("/")
        self.timeout = timeout
        self.access_window_ms = access_window_ms
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.rate_limit_buffer = rate_limit_buffer
        self.wait_on_rate_limit = wait_on_rate_limit
        self.user_agent = user_agent or (
            f"bitvavo-sdk-python/{__version__} python/{platform.python_version()}"
        )
        #: Milliseconds to add to local time so it matches Bitvavo's clock.
        #: Set by :meth:`sync_time`, and automatically after an errorCode 304.
        self.time_offset_ms = 0
        #: Budget reported by the most recent response.
        self.rate_limit = RateLimitState()

    @classmethod
    def from_env(cls: Type[_C], **kwargs: Any) -> _C:
        """Create a client from ``BITVAVO_API_KEY``, ``BITVAVO_API_SECRET``,
        ``BITVAVO_OPERATOR_ID`` and ``BITVAVO_BASE_URL``. Keyword arguments win."""
        env = os.environ
        kwargs.setdefault("api_key", env.get("BITVAVO_API_KEY") or None)
        kwargs.setdefault("api_secret", env.get("BITVAVO_API_SECRET") or None)
        if env.get("BITVAVO_OPERATOR_ID"):
            kwargs.setdefault("operator_id", int(env["BITVAVO_OPERATOR_ID"]))
        if env.get("BITVAVO_BASE_URL"):
            kwargs.setdefault("base_url", env["BITVAVO_BASE_URL"])
        return cls(**kwargs)

    @property
    def has_credentials(self) -> bool:
        return self._api_key is not None

    def __repr__(self) -> str:
        key = f"{self._api_key[:4]}..." if self._api_key else None
        return f"{type(self).__name__}(api_key={key!r}, base_url={self.base_url!r})"

    # -- request building ------------------------------------------------------

    def _now_ms(self) -> int:
        return int(time.time() * 1000) + self.time_offset_ms

    def _operator(self, operator_id: Optional[int]) -> int:
        op = self.operator_id if operator_id is None else operator_id
        if op is None:
            raise ValueError(
                "operatorId is required for order requests: pass operator_id= to the "
                "client or to this call"
            )
        return int(op)

    def _prepare(
        self,
        method: str,
        path: str,
        params: Optional[Mapping[str, Any]],
        body: Optional[Mapping[str, Any]],
        private: bool,
        weight: int,
    ) -> PreparedRequest:
        query = urlencode(_clean_query(params)) if params else ""
        full_path = f"{path}?{query}" if query else path
        content = json.dumps(_clean_body(body), separators=(",", ":")) if body is not None else None
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        if content is not None:
            headers["Content-Type"] = "application/json"
        if private and not self.has_credentials:
            raise MissingCredentialsError(f"{method} {path} requires api_key and api_secret")
        if self._api_key is not None and self._api_secret is not None:
            headers.update(
                auth_headers(
                    self._api_key,
                    self._api_secret,
                    self._now_ms(),
                    method,
                    self._sign_prefix + full_path,
                    content or "",
                    self.access_window_ms,
                )
            )
        return PreparedRequest(method, self.base_url + full_path, headers, content, weight)

    # -- response handling -----------------------------------------------------

    def _handle(self, response: httpx.Response) -> Any:
        self.rate_limit.update(response.headers)
        if response.is_success:
            if not response.content:
                return None
            return response.json()
        if response.status_code == 429:
            # Blocked: make the next call wait for reset_at instead of hitting the ban.
            self.rate_limit.remaining = 0
        raise error_from_response(response, reset_at=self.rate_limit.reset_at)

    def _rate_limit_wait(self, weight: int) -> float:
        if not self.wait_on_rate_limit:
            return 0.0
        wait = self.rate_limit.wait_needed(weight, self.rate_limit_buffer, self._now_ms())
        if wait > 0:
            logger.warning("rate limit budget low; sleeping %.1fs until reset", wait)
        return wait

    def _after_rate_limit_wait(self) -> None:
        # The window has reset; the real budget is unknown until the next response.
        self.rate_limit.remaining = None

    def _should_retry_error(self, method: str, error: APIError) -> bool:
        if error.error_code in _SAFE_RETRY_CODES:
            return True
        return method == "GET" and error.status_code >= 500

    def _backoff(self, attempt: int) -> float:
        return float(self.retry_backoff * (2 ** (attempt - 1)))

    def _log(self, req: PreparedRequest, status: object, started: float) -> None:
        if logger.isEnabledFor(logging.DEBUG):
            path = req.url[len(self.base_url) :]
            logger.debug(
                "%s %s -> %s (%.0f ms, weight %d, remaining %s)",
                req.method,
                path,
                status,
                (time.monotonic() - started) * 1000,
                req.weight,
                self.rate_limit.remaining,
            )


def _num(value: Optional[Number]) -> Optional[str]:
    return None if value is None else format_number(value)


def _clean_query(params: Mapping[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            out[key] = "true" if value else "false"
        else:
            out[key] = str(value)
    return out


def _clean_body(body: Mapping[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in body.items() if v is not None}
