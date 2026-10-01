"""Translate the REST endpoint layer's ``(method, path)`` calls into WebSocket actions.

The WebSocket client inherits every typed endpoint method from the REST endpoint
layer; only the transport differs. Parameter names are identical on both APIs.
"""

from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

from .errors import BitvavoError

_STATIC: Dict[Tuple[str, str], str] = {
    ("GET", "/time"): "getTime",
    ("GET", "/markets"): "getMarkets",
    ("GET", "/assets"): "getAssets",
    ("GET", "/ticker/price"): "getTickerPrice",
    ("GET", "/ticker/book"): "getTickerBook",
    ("GET", "/ticker/24h"): "getTicker24h",
    ("POST", "/order"): "privateCreateOrder",
    ("PUT", "/order"): "privateUpdateOrder",
    ("DELETE", "/order"): "privateCancelOrder",
    ("GET", "/order"): "privateGetOrder",
    ("GET", "/orders"): "privateGetOrders",
    ("DELETE", "/orders"): "privateCancelOrders",
    ("DELETE", "/atomic/orders"): "privateAtomicCancelOrders",
    ("POST", "/cancelOrdersAfter"): "privateCancelOrdersAfter",
    ("GET", "/ordersOpen"): "privateGetOrdersOpen",
    ("GET", "/trades"): "privateGetTrades",
    ("GET", "/account"): "privateGetAccount",
    ("GET", "/account/fees"): "privateGetFees",
    ("GET", "/balance"): "privateGetBalance",
    ("GET", "/account/history"): "privateGetTransactionHistory",
    ("GET", "/deposit"): "privateDepositAssets",
    ("GET", "/depositHistory"): "privateGetDepositHistory",
    ("GET", "/withdrawalHistory"): "privateGetWithdrawalHistory",
    ("POST", "/withdrawal"): "privateWithdrawAssets",
    ("POST", "/crypto/withdrawal"): "privateCryptoWithdrawal",
}

# REST paths with the market in the path; on the WebSocket it is a parameter.
_MARKET_PATH = re.compile(r"^/(?P<market>[^/]+)/(?P<kind>book|trades|candles)$")
_MARKET_ACTIONS = {"book": "getBook", "trades": "getTrades", "candles": "getCandles"}


class NotAvailableOverWebSocket(BitvavoError):
    """The endpoint exists only on the REST API (e.g. staking balance, MiCA reports)."""


def route(method: str, path: str) -> Tuple[str, Optional[str]]:
    """Return ``(action, market_from_path)`` for a REST call."""
    action = _STATIC.get((method, path))
    if action is not None:
        return action, None
    m = _MARKET_PATH.match(path)
    if method == "GET" and m:
        from urllib.parse import unquote

        return _MARKET_ACTIONS[m["kind"]], unquote(m["market"])
    raise NotAvailableOverWebSocket(
        f"{method} {path} is not available over the WebSocket API; use the REST client"
    )
