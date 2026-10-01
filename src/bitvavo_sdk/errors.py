"""Exception hierarchy.

Every exception raised by this SDK derives from :class:`BitvavoError`, so a single
``except BitvavoError`` catches everything. Errors returned by the API are
:class:`APIError` subclasses chosen by HTTP status and Bitvavo ``errorCode``; see
https://docs.bitvavo.com/docs/errors/ for the full code list.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Type

import httpx


class BitvavoError(Exception):
    """Base class for all SDK errors."""


class MissingCredentialsError(BitvavoError):
    """A private endpoint was called on a client created without API key/secret."""


class TransportError(BitvavoError):
    """The request never produced an HTTP response (DNS, connect, TLS, read timeout...).

    For order-changing requests the outcome is **unknown**: query the order before
    retrying to avoid duplicates.
    """


class APIError(BitvavoError):
    """Bitvavo answered with a non-2xx status.

    Attributes:
        status_code: HTTP status code.
        error_code: Bitvavo ``errorCode`` (``None`` if the body was not JSON).
        message: Bitvavo ``error`` text.
        body: Parsed JSON body, or raw text if it was not JSON.
        response: The underlying :class:`httpx.Response`.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        error_code: Optional[int],
        body: Any = None,
        response: Optional[httpx.Response] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.body = body
        self.response = response

    def __str__(self) -> str:
        return f"[HTTP {self.status_code}, errorCode {self.error_code}] {self.message}"


class BadRequestError(APIError):
    """HTTP 400: invalid parameters or order rejected. Do not retry unchanged."""


class InsufficientBalanceError(BadRequestError):
    """errorCode 216 / 408: not enough balance."""


class AuthenticationError(APIError):
    """HTTP 403 with errorCode 300-309: missing/invalid key, signature or timestamp."""


class PermissionDeniedError(APIError):
    """HTTP 403 for permission/account problems (errorCode 310+, 5xx-range admin codes)."""


class NotFoundError(APIError):
    """HTTP 404, e.g. errorCode 240 (order does not exist or is no longer active)."""


class MarketNotTradingError(APIError):
    """The market is not in ``trading`` status (errorCode 423-426 and 431).

    Typical for freshly listed markets that are still in ``auction``.
    """


class RateLimitError(APIError):
    """HTTP 429 / errorCode 105: you are blocked until :attr:`reset_at` (ms epoch)."""

    def __init__(self, message: str, *, reset_at: Optional[int] = None, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.reset_at = reset_at


class ServerError(APIError):
    """HTTP 5xx. errorCode 109 means the outcome is unknown: check state before retrying."""


_MARKET_STATUS_CODES = {423, 424, 425, 426, 431}
_BALANCE_CODES = {216, 408}

_BY_STATUS: Dict[int, Type[APIError]] = {
    400: BadRequestError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: MarketNotTradingError,
    429: RateLimitError,
}


def error_class_for(status_code: int, error_code: Optional[int]) -> Type[APIError]:
    """Pick the most specific exception class for a status/errorCode pair."""
    if error_code in _MARKET_STATUS_CODES:
        return MarketNotTradingError
    if error_code in _BALANCE_CODES:
        return InsufficientBalanceError
    if status_code == 403 and error_code is not None and 300 <= error_code <= 309:
        return AuthenticationError
    if status_code >= 500:
        return ServerError
    return _BY_STATUS.get(status_code, APIError)


def error_from_response(response: httpx.Response, reset_at: Optional[int] = None) -> APIError:
    """Build the exception for a failed response."""
    body: Any
    try:
        body = response.json()
    except ValueError:
        body = response.text
    error_code: Optional[int] = None
    message = response.reason_phrase or "Unknown error"
    if isinstance(body, dict):
        raw_code = body.get("errorCode")
        if isinstance(raw_code, int):
            error_code = raw_code
        message = str(body.get("error", message))
    elif body:
        message = str(body)[:500]
    cls = error_class_for(response.status_code, error_code)
    kwargs: Dict[str, Any] = {
        "status_code": response.status_code,
        "error_code": error_code,
        "body": body,
        "response": response,
    }
    if issubclass(cls, RateLimitError):
        return cls(message, reset_at=reset_at, **kwargs)
    return cls(message, **kwargs)


# The WebSocket API reports only an errorCode; derive the HTTP-equivalent status from
# Bitvavo's error table so both transports raise the same exception classes.
_SERVER_CODES = {101, 107, 108, 109, 111, 400, 419, 430}
_NOT_FOUND_CODES = {240, 415, 510}
_FORBIDDEN_CODES = set(range(300, 323)) | set(range(511, 515))


def status_for_error_code(error_code: Optional[int]) -> int:
    """HTTP status Bitvavo's REST API would use for ``error_code``."""
    if error_code in (105, 112):
        return 429
    if error_code in _SERVER_CODES:
        return 503 if error_code != 400 else 500
    if error_code in _NOT_FOUND_CODES:
        return 404
    if error_code in _FORBIDDEN_CODES:
        return 403
    if error_code == 431:
        return 409
    return 400


def error_from_payload(payload: Dict[str, Any]) -> APIError:
    """Build the exception for a WebSocket error message."""
    raw_code = payload.get("errorCode")
    error_code = raw_code if isinstance(raw_code, int) else None
    status = status_for_error_code(error_code)
    cls = error_class_for(status, error_code)
    message = str(payload.get("error", "Unknown error"))
    return cls(message, status_code=status, error_code=error_code, body=payload)
