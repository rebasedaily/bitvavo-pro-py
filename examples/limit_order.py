"""Place a post-only limit buy 5% under the best bid, then cancel it.

Needs BITVAVO_API_KEY, BITVAVO_API_SECRET and BITVAVO_OPERATOR_ID. Places a REAL order
(far from the market, and canceled right away), so it costs nothing if all goes well.
"""

import uuid
from decimal import Decimal

from bitvavo_sdk import Bitvavo, BitvavoError, round_to_decimals, round_to_tick

MARKET = "BTC-EUR"

with Bitvavo.from_env() as client:
    info = client.get_market(MARKET)
    bid = Decimal(client.get_ticker_book(MARKET)["bid"])
    price = round_to_tick(bid * Decimal("0.95"), info["tickSize"], "down")
    amount = round_to_decimals(
        Decimal(info["minOrderInQuoteAsset"]) * 2 / price, info["quantityDecimals"], "up"
    )

    order = client.limit_buy(
        MARKET, amount, price, post_only=True, client_order_id=str(uuid.uuid4())
    )
    print("placed", order["orderId"], order["status"], amount, "@", price)
    try:
        print("open orders:", len(client.get_open_orders(MARKET)))
    except BitvavoError as exc:
        print("could not list orders:", exc)
    finally:
        print("canceled", client.cancel_order(MARKET, order_id=order["orderId"]))
