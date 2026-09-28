"""Live order lifecycle test: places REAL orders on BTC-EUR, then cancels them.

Opt-in only. Runs when BITVAVO_LIVE_ORDERS=1 and credentials are available in the
environment or in ``.env.prod`` at the repository root:

    BITVAVO_LIVE_ORDERS=1 pytest tests/test_live_orders.py -v -s

What it does, and the safety rails around it:

* Only post-only limit orders about 20% away from the market: they cannot fill,
  and post-only makes Bitvavo cancel rather than execute if they ever would.
* Order size is just above the market minimum (about 5 EUR).
* An httpx hook allows only: GETs, and POST/PUT/DELETE on ``/v2/order`` with
  market BTC-EUR. Anything else, notably ``DELETE /orders`` (which would cancel
  *your own* orders too) or withdrawals, is refused before it is sent.
* Every order created is canceled in a ``finally`` block, even if assertions fail.
"""

from __future__ import annotations

import json
import os
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Dict, List

import httpx
import pytest

from bitvavo_sdk import Bitvavo, NotFoundError, round_to_decimals, round_to_tick

MARKET = "BTC-EUR"
OPERATOR_ID = int(os.environ.get("BITVAVO_OPERATOR_ID", "9001"))
DISTANCE = Decimal("0.20")  # 20% away from the market


def _load_env_file(name: str) -> Dict[str, str]:
    path = Path(__file__).resolve().parent.parent / name
    values: Dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip("'\"")
    return values


_ENV = {**_load_env_file(".env.prod"), **os.environ}
_KEY, _SECRET = _ENV.get("BITVAVO_API_KEY"), _ENV.get("BITVAVO_API_SECRET")

pytestmark = pytest.mark.skipif(
    os.environ.get("BITVAVO_LIVE_ORDERS") != "1" or not (_KEY and _SECRET),
    reason="places real orders: set BITVAVO_LIVE_ORDERS=1 and credentials (.env.prod)",
)


class GuardViolation(AssertionError):
    pass


def _guard(request: httpx.Request) -> None:
    if request.method == "GET":
        return
    if request.url.path != "/v2/order":
        raise GuardViolation(f"blocked {request.method} {request.url.path}")
    market = request.url.params.get("market")
    if request.content:
        market = json.loads(request.content).get("market")
    if market != MARKET:
        raise GuardViolation(f"blocked {request.method} /order for market {market!r}")


@pytest.fixture(scope="module")
def client():
    http = httpx.Client(timeout=10, event_hooks={"request": [_guard]})
    c = Bitvavo(_KEY, _SECRET, operator_id=OPERATOR_ID, http_client=http)
    c.sync_time()
    yield c
    http.close()


@pytest.fixture
def created(client):
    """Order ids to cancel no matter how the test ends."""
    ids: List[str] = []
    yield ids
    for order_id in ids:
        try:
            client.cancel_order(MARKET, order_id=order_id)
            print(f"  cleanup: canceled {order_id}")
        except NotFoundError:
            pass  # already canceled by the test


def _size(client: Bitvavo, price: Decimal) -> Decimal:
    info = client.get_market(MARKET)
    min_quote = Decimal(info["minOrderInQuoteAsset"]) * Decimal("1.1")
    amount = max(Decimal(info["minOrderInBaseAsset"]), min_quote / price)
    return round_to_decimals(amount, info["quantityDecimals"], "up")


def _available(client: Bitvavo, symbol: str) -> Decimal:
    bal = client.get_balance(symbol)
    return Decimal(bal[0]["available"]) if bal else Decimal(0)


def test_guard_refuses_bulk_cancel_and_other_markets(client):
    with pytest.raises(GuardViolation):
        client.cancel_orders(MARKET)  # would cancel the user's own orders too
    with pytest.raises(GuardViolation):
        client.limit_buy("ETH-EUR", "1", "1", post_only=True)


def _lifecycle(client: Bitvavo, created: List[str], side: str) -> None:
    info = client.get_market(MARKET)
    tick = info["tickSize"]
    book = client.get_ticker_book(MARKET)
    if side == "buy":
        price = round_to_tick(Decimal(book["bid"]) * (1 - DISTANCE), tick, "down")
    else:
        price = round_to_tick(Decimal(book["ask"]) * (1 + DISTANCE), tick, "up")
    amount = _size(client, price)
    coid = str(uuid.uuid4())
    print(f"\n  {side} {amount} {MARKET} @ {price} (~{(amount * price):.2f} EUR), post-only")

    # 1. create
    place = client.limit_buy if side == "buy" else client.limit_sell
    order = place(MARKET, amount, price, post_only=True, client_order_id=coid)
    created.append(order["orderId"])
    print(f"  created {order['orderId']} status={order['status']}")
    assert order["status"] == "new", order.get("restatementReason")
    assert order["clientOrderId"] == coid
    assert order["operatorId"] == OPERATOR_ID
    assert Decimal(order["price"]) == price and Decimal(order["amount"]) == amount
    assert Decimal(order["filledAmount"]) == 0

    # 2. read back, by orderId and by clientOrderId. find_order, because Bitvavo's
    #    GET /order returns 240 for a few hundred ms after creation.
    by_id = client.find_order(MARKET, order_id=order["orderId"])
    by_coid = client.find_order(MARKET, client_order_id=coid)
    assert by_id is not None and by_coid is not None
    assert by_id["orderId"] == by_coid["orderId"] == order["orderId"]
    open_ids = {o["orderId"] for o in client.get_open_orders(MARKET)}
    assert order["orderId"] in open_ids

    # 3. update the price in place (one more tick away from the market)
    step = Decimal(tick) * (-1 if side == "buy" else 1)
    new_price = price + step
    updated = client.update_order(MARKET, order_id=order["orderId"], price=new_price)
    print(f"  updated price {price} -> {updated['price']}")
    assert Decimal(updated["price"]) == new_price
    assert updated["orderId"] == order["orderId"]

    # 4. cancel
    canceled = client.cancel_order(MARKET, order_id=order["orderId"])
    assert canceled["orderId"] == order["orderId"]
    final = client.find_order(MARKET, order_id=order["orderId"], status={"canceled", "filled"})
    assert final is not None
    print(f"  canceled, final status={final['status']}, filled={final['filledAmount']}")
    assert final["status"] == "canceled"
    assert Decimal(final["filledAmount"]) == 0

    # 5. a second cancel maps to NotFoundError (errorCode 240)
    with pytest.raises(NotFoundError) as info_err:
        client.cancel_order(MARKET, order_id=order["orderId"])
    assert info_err.value.error_code == 240


def test_buy_order_lifecycle(client, created):
    book = client.get_ticker_book(MARKET)
    need = _size(client, Decimal(book["bid"]) * (1 - DISTANCE)) * Decimal(book["bid"])
    if _available(client, "EUR") < need:
        pytest.skip(f"needs about {need:.2f} EUR available to place a resting buy")
    _lifecycle(client, created, "buy")


def test_sell_order_lifecycle(client, created):
    book = client.get_ticker_book(MARKET)
    need = _size(client, Decimal(book["ask"]) * (1 + DISTANCE))
    if _available(client, "BTC") < need:
        pytest.skip(f"needs {need} BTC available to place a resting sell")
    _lifecycle(client, created, "sell")
