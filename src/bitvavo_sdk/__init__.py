"""Python SDK for the Bitvavo Exchange REST API.

Quick start::

    from bitvavo_sdk import Bitvavo

    client = Bitvavo.from_env()                    # BITVAVO_API_KEY / _SECRET / _OPERATOR_ID
    print(client.get_ticker_price("BTC-EUR"))
    client.market_buy("BTC-EUR", amount_quote="10")
"""

from ._version import __version__
from .async_client import AsyncBitvavo
from .auth import create_signature
from .client import Bitvavo
from .errors import (
    APIError,
    AuthenticationError,
    BadRequestError,
    BitvavoError,
    InsufficientBalanceError,
    MarketNotTradingError,
    MissingCredentialsError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServerError,
    TransportError,
)
from .rate_limit import RateLimitState
from .utils import format_number, round_to_decimals, round_to_tick

__all__ = [
    "APIError",
    "AsyncBitvavo",
    "AuthenticationError",
    "BadRequestError",
    "Bitvavo",
    "BitvavoError",
    "InsufficientBalanceError",
    "MarketNotTradingError",
    "MissingCredentialsError",
    "NotFoundError",
    "PermissionDeniedError",
    "RateLimitError",
    "RateLimitState",
    "ServerError",
    "TransportError",
    "__version__",
    "create_signature",
    "format_number",
    "round_to_decimals",
    "round_to_tick",
]
