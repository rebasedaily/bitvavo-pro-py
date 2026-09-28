"""Request signing for the Bitvavo REST API.

Bitvavo signs ``timestamp + METHOD + path + body`` with HMAC-SHA256, hex encoded,
where ``path`` includes the ``/v2`` prefix and the query string, and ``body`` is
the exact JSON string sent (empty for requests without a body).
See https://docs.bitvavo.com/docs/rest-api/introduction/.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Dict


def create_signature(secret: str, timestamp: int, method: str, path: str, body: str = "") -> str:
    """Return the ``Bitvavo-Access-Signature`` value.

    Args:
        secret: API secret.
        timestamp: Unix time in milliseconds, identical to ``Bitvavo-Access-Timestamp``.
        method: HTTP method, e.g. ``"POST"``.
        path: Request path including ``/v2`` and any query string, e.g. ``"/v2/order"``.
        body: Exact request body string, ``""`` when there is none.
    """
    message = f"{timestamp}{method.upper()}{path}{body}"
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def auth_headers(
    api_key: str,
    secret: str,
    timestamp: int,
    method: str,
    path: str,
    body: str = "",
    access_window_ms: int = 10_000,
) -> Dict[str, str]:
    """Return the full set of authentication headers for one request."""
    return {
        "Bitvavo-Access-Key": api_key,
        "Bitvavo-Access-Signature": create_signature(secret, timestamp, method, path, body),
        "Bitvavo-Access-Timestamp": str(timestamp),
        "Bitvavo-Access-Window": str(access_window_ms),
    }
