"""Print the EUR markets with the biggest 24h moves. No API key needed."""

from decimal import Decimal

from bitvavo_sdk import Bitvavo

with Bitvavo() as client:
    tickers = client.get_tickers_24h()  # weight 25: one call for every market
    moves = []
    for t in tickers:
        if t["market"].endswith("-EUR") and t.get("open") and t.get("last"):
            opened, last = Decimal(t["open"]), Decimal(t["last"])
            if opened > 0:
                moves.append(((last - opened) / opened * 100, t["market"], last))
    for pct, market, last in sorted(moves, reverse=True)[:10]:
        print(f"{market:<12} {last:>14}  {pct:+.2f}%")
    print("rate limit remaining:", client.rate_limit.remaining)
