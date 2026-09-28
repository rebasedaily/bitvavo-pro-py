# Getting started

## Install

```bash
pip install bitvavo-sdk
```

The SDK needs Python 3.9 or newer. Its only runtime dependency is `httpx`.

## Public data: no account needed

Public endpoints work without credentials. Unauthenticated requests are rate-limited per IP address, and a ban lasts 15 minutes instead of 1, so pass a key once you start polling frequently.

```python
from bitvavo_sdk import Bitvavo

with Bitvavo() as client:
    print(client.get_time())  # {'time': 1790586487070, 'timeNs': ...}

    for m in client.get_markets():
        if m["quote"] == "EUR" and m["status"] == "trading":
            print(m["market"], m["tickSize"], m["minOrderInQuoteAsset"])

    book = client.get_order_book("BTC-EUR", depth=5)
    best_bid, best_ask = book["bids"][0][0], book["asks"][0][0]
```

All monetary values arrive as **strings**. Convert them with `decimal.Decimal`, never with `float`.

## Create an API key

1. In the Bitvavo dashboard, go to **Settings → API** and create a key.
2. Grant only the permissions you need:
    - **View**: balances, orders and history.
    - **Trade**: create, update and cancel orders. Order and trade *queries* need both View and Trade.
    - **Withdraw**: avoid this one. API withdrawals skip 2FA and e-mail confirmation.
3. Restrict the key to your server's IP addresses.
4. Store the secret somewhere safe. It's shown only once.

## Authenticated calls

```python
import os
from bitvavo_sdk import Bitvavo

client = Bitvavo(
    api_key=os.environ["BITVAVO_API_KEY"],
    api_secret=os.environ["BITVAVO_API_SECRET"],
    operator_id=1001,
)
# or equivalently:
client = Bitvavo.from_env()  # reads BITVAVO_API_KEY, BITVAVO_API_SECRET, BITVAVO_OPERATOR_ID

for b in client.get_balance():
    print(b["symbol"], b["available"], b["inOrder"])
```

### What is `operator_id`?

Bitvavo requires an `operatorId` on every create, update and cancel request. It's an integer that you choose to identify which trader or bot in your account placed the order, and it's echoed back on orders and fills. Set it once on the client, or override it per call with `operator_id=`.

## Place your first order

```python
from decimal import Decimal
from bitvavo_sdk import round_to_tick, round_to_decimals

market = client.get_market("ETH-EUR")

# Spend exactly 10 EUR at market price
order = client.market_buy("ETH-EUR", amount_quote="10")
print(order["status"], order["filledAmount"], order["feePaid"])

# A limit sell 5% above the last price, rounded to what the market accepts
last = Decimal(client.get_ticker_price("ETH-EUR")["price"])
price = round_to_tick(last * Decimal("1.05"), market["tickSize"], "up")
amount = round_to_decimals(order["filledAmount"], market["quantityDecimals"])
client.limit_sell("ETH-EUR", amount, price)
```

Next: [Configuration](configuration.md) · [Error handling](errors.md) · [Endpoint reference](endpoints.md)
