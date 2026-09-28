"""Every Bitvavo REST endpoint, written once as synchronous code.

``_async_endpoints.py`` is generated from this file by ``scripts/generate_async.py``;
edit this file and re-run the script, never the generated one.

Rate limit weights are from https://docs.bitvavo.com/docs/rest-api/.
"""

from __future__ import annotations

import time
from typing import Any, Collection, Dict, Iterator, List, Optional, cast
from urllib.parse import quote

from ._base import BaseClient, _num
from .errors import NotFoundError
from .types import (
    Account,
    AccountTrade,
    Asset,
    Balance,
    CanceledOrder,
    CancelOrdersAfter,
    Candle,
    CandleInterval,
    CryptoWithdrawalResult,
    DepositData,
    Market,
    MarketFees,
    Number,
    Order,
    OrderBook,
    OrderType,
    PublicTrade,
    SelfTradePrevention,
    ServerTime,
    Side,
    StakingBalance,
    Ticker24h,
    TickerBook,
    TickerPrice,
    TimeInForce,
    Transaction,
    TransactionHistory,
    TransactionType,
    TransferRecord,
    TriggerReference,
    TriggerType,
    WithdrawalResult,
)


def _m(market: str) -> str:
    return quote(market, safe="")


def _one(result: Any) -> Any:
    """Bitvavo returns an object or a one-element list when filtering by market."""
    if isinstance(result, list):
        return result[0] if result else None
    return result


class SyncEndpoints(BaseClient):
    def _call(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
        private: bool = False,
        weight: int = 1,
    ) -> Any:
        raise NotImplementedError

    # ------------------------------------------------------------------ general

    def get_time(self) -> ServerTime:
        """Bitvavo server time. ``GET /time`` (weight 1)."""
        return cast(ServerTime, self._call("GET", "/time"))

    def sync_time(self) -> int:
        """Measure the offset between the local clock and Bitvavo's and store it in
        :attr:`time_offset_ms`, used for every signed request afterwards.

        Returns:
            The offset in milliseconds (positive when the local clock is behind).
        """
        self.time_offset_ms = 0
        started = time.time()
        server = self._call("GET", "/time")
        local_mid = (started + time.time()) / 2 * 1000
        self.time_offset_ms = int(server["time"] - local_mid)
        return self.time_offset_ms

    def get_markets(self) -> List[Market]:
        """All markets with status, limits, ``tickSize`` and decimals.
        ``GET /markets`` (weight 1).

        New listings show up here first, usually in ``auction`` status before they
        switch to ``trading``.
        """
        return cast(List[Market], self._call("GET", "/markets"))

    def get_market(self, market: str) -> Market:
        """One market, e.g. ``"BTC-EUR"``. ``GET /markets?market=`` (weight 1)."""
        return cast(Market, _one(self._call("GET", "/markets", params={"market": market})))

    def get_assets(self) -> List[Asset]:
        """All assets with deposit/withdrawal status and fees. ``GET /assets`` (weight 1)."""
        return cast(List[Asset], self._call("GET", "/assets"))

    def get_asset(self, symbol: str) -> Asset:
        """One asset, e.g. ``"BTC"``. ``GET /assets?symbol=`` (weight 1)."""
        return cast(Asset, _one(self._call("GET", "/assets", params={"symbol": symbol})))

    # -------------------------------------------------------------- market data

    def get_order_book(self, market: str, *, depth: Optional[int] = None) -> OrderBook:
        """Bids and asks as ``[price, amount]`` pairs, best first.
        ``GET /{market}/book`` (weight 1).

        Args:
            depth: Number of levels per side, max 1000 (default 1000).
        """
        return cast(OrderBook, self._call("GET", f"/{_m(market)}/book", params={"depth": depth}))

    def get_trades(
        self,
        market: str,
        *,
        limit: Optional[int] = None,
        start: Optional[int] = None,
        end: Optional[int] = None,
        trade_id_from: Optional[str] = None,
        trade_id_to: Optional[str] = None,
    ) -> List[PublicTrade]:
        """Public trades of all users, newest first, window of at most 24h.
        ``GET /{market}/trades`` (weight 5).

        Args:
            limit: 1-1000, default 500.
            start: Unix ms (inclusive).
            end: Unix ms, at most 24h after ``start``.
        """
        params = {
            "limit": limit,
            "start": start,
            "end": end,
            "tradeIdFrom": trade_id_from,
            "tradeIdTo": trade_id_to,
        }
        return cast(
            List[PublicTrade],
            self._call("GET", f"/{_m(market)}/trades", params=params, weight=5),
        )

    def get_candles(
        self,
        market: str,
        interval: CandleInterval,
        *,
        limit: Optional[int] = None,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> List[Candle]:
        """OHLCV candles ``[timestamp, open, high, low, close, volume]``, newest first.
        ``GET /{market}/candles`` (weight 1).

        Args:
            interval: ``1m 5m 15m 30m 1h 2h 4h 6h 8h 12h 1d 1W 1M``.
            limit: 1-1440, default 1440.
            start: Unix ms aligned to the interval start.
            end: Unix ms aligned to the interval end.
        """
        params = {"interval": interval, "limit": limit, "start": start, "end": end}
        return cast(List[Candle], self._call("GET", f"/{_m(market)}/candles", params=params))

    def get_ticker_prices(self) -> List[TickerPrice]:
        """Last trade price for every market. ``GET /ticker/price`` (weight 1)."""
        return cast(List[TickerPrice], self._call("GET", "/ticker/price"))

    def get_ticker_price(self, market: str) -> TickerPrice:
        """Last trade price for one market. ``GET /ticker/price?market=`` (weight 1)."""
        return cast(
            TickerPrice, _one(self._call("GET", "/ticker/price", params={"market": market}))
        )

    def get_ticker_books(self) -> List[TickerBook]:
        """Best bid/ask for every market. ``GET /ticker/book`` (weight 1)."""
        return cast(List[TickerBook], self._call("GET", "/ticker/book"))

    def get_ticker_book(self, market: str) -> TickerBook:
        """Best bid/ask for one market. ``GET /ticker/book?market=`` (weight 1)."""
        return cast(TickerBook, _one(self._call("GET", "/ticker/book", params={"market": market})))

    def get_tickers_24h(self) -> List[Ticker24h]:
        """24h OHLCV statistics for every market. ``GET /ticker/24h`` (weight 25)."""
        return cast(List[Ticker24h], self._call("GET", "/ticker/24h", weight=25))

    def get_ticker_24h(self, market: str) -> Ticker24h:
        """24h OHLCV statistics for one market. ``GET /ticker/24h?market=`` (weight 1)."""
        return cast(Ticker24h, _one(self._call("GET", "/ticker/24h", params={"market": market})))

    def get_order_book_report(self, market: str, *, depth: Optional[int] = None) -> Dict[str, Any]:
        """MiCA-compliant order book report. ``GET /report/{market}/book`` (weight 1)."""
        return cast(
            Dict[str, Any],
            self._call("GET", f"/report/{_m(market)}/book", params={"depth": depth}),
        )

    def get_trades_report(
        self,
        market: str,
        *,
        limit: Optional[int] = None,
        start: Optional[int] = None,
        end: Optional[int] = None,
        trade_id_from: Optional[str] = None,
        trade_id_to: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """MiCA-compliant public trades report. ``GET /report/{market}/trades`` (weight 5)."""
        params = {
            "limit": limit,
            "start": start,
            "end": end,
            "tradeIdFrom": trade_id_from,
            "tradeIdTo": trade_id_to,
        }
        return cast(
            List[Dict[str, Any]],
            self._call("GET", f"/report/{_m(market)}/trades", params=params, weight=5),
        )

    # ------------------------------------------------------------------ trading

    def create_order(
        self,
        market: str,
        side: Side,
        order_type: OrderType,
        *,
        amount: Optional[Number] = None,
        amount_quote: Optional[Number] = None,
        price: Optional[Number] = None,
        trigger_amount: Optional[Number] = None,
        trigger_type: Optional[TriggerType] = None,
        trigger_reference: Optional[TriggerReference] = None,
        time_in_force: Optional[TimeInForce] = None,
        post_only: Optional[bool] = None,
        self_trade_prevention: Optional[SelfTradePrevention] = None,
        client_order_id: Optional[str] = None,
        response_required: Optional[bool] = None,
        cod_group_id: Optional[int] = None,
        operator_id: Optional[int] = None,
    ) -> Order:
        """Place an order. ``POST /order`` (weight 1). Max 100 open orders per market.

        Args:
            market: e.g. ``"BTC-EUR"``.
            side: ``"buy"`` or ``"sell"``.
            order_type: ``market``, ``limit``, ``stopLoss``, ``stopLossLimit``,
                ``takeProfit`` or ``takeProfitLimit``.
            amount: Base currency quantity (max ``quantityDecimals`` decimals).
            amount_quote: Quote currency quantity, for market/stopLoss/takeProfit
                orders (max ``notionalDecimals`` decimals). Use either this or ``amount``.
            price: Limit price, a multiple of the market ``tickSize``.
            trigger_amount: Trigger price for stop/take-profit orders.
            trigger_type: ``"price"``.
            trigger_reference: ``lastTrade``, ``bestBid``, ``bestAsk`` or ``midPrice``.
            time_in_force: ``GTC`` (default), ``IOC`` or ``FOK``.
            post_only: Cancel instead of taking liquidity.
            self_trade_prevention: Defaults to ``decrementAndCancel``.
            client_order_id: Your UUID for the order, unique among open orders.
            response_required: ``False`` returns only ids and timestamps (faster).
            cod_group_id: Cancel-on-disconnect group (1-1000).
            operator_id: Overrides the client's default ``operatorId``.

        Raises:
            TransportError: The request may or may not have reached Bitvavo. Look the
                order up (use ``client_order_id``) before placing it again.
        """
        body: Dict[str, Any] = {
            "market": market,
            "side": side,
            "orderType": order_type,
            "operatorId": self._operator(operator_id),
            "clientOrderId": client_order_id,
            "amount": _num(amount),
            "amountQuote": _num(amount_quote),
            "price": _num(price),
            "triggerAmount": _num(trigger_amount),
            "triggerType": trigger_type,
            "triggerReference": trigger_reference,
            "timeInForce": time_in_force,
            "postOnly": post_only,
            "selfTradePrevention": self_trade_prevention,
            "responseRequired": response_required,
            "codGroupId": cod_group_id,
        }
        return cast(Order, self._call("POST", "/order", body=body, private=True))

    def market_buy(
        self,
        market: str,
        *,
        amount: Optional[Number] = None,
        amount_quote: Optional[Number] = None,
        **kwargs: Any,
    ) -> Order:
        """Buy at market price. Pass ``amount_quote`` to spend a fixed quote amount
        (e.g. ``amount_quote="25"`` spends 25 EUR). Extra kwargs go to :meth:`create_order`.
        """
        _require_one(amount=amount, amount_quote=amount_quote)
        return self.create_order(
            market, "buy", "market", amount=amount, amount_quote=amount_quote, **kwargs
        )

    def market_sell(
        self,
        market: str,
        *,
        amount: Optional[Number] = None,
        amount_quote: Optional[Number] = None,
        **kwargs: Any,
    ) -> Order:
        """Sell at market price, either ``amount`` of base or for ``amount_quote`` of quote."""
        _require_one(amount=amount, amount_quote=amount_quote)
        return self.create_order(
            market, "sell", "market", amount=amount, amount_quote=amount_quote, **kwargs
        )

    def limit_buy(self, market: str, amount: Number, price: Number, **kwargs: Any) -> Order:
        """Buy ``amount`` of base at ``price`` or better (GTC unless ``time_in_force``)."""
        return self.create_order(market, "buy", "limit", amount=amount, price=price, **kwargs)

    def limit_sell(self, market: str, amount: Number, price: Number, **kwargs: Any) -> Order:
        """Sell ``amount`` of base at ``price`` or better (GTC unless ``time_in_force``)."""
        return self.create_order(market, "sell", "limit", amount=amount, price=price, **kwargs)

    def update_order(
        self,
        market: str,
        *,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
        amount: Optional[Number] = None,
        amount_quote: Optional[Number] = None,
        amount_remaining: Optional[Number] = None,
        price: Optional[Number] = None,
        trigger_amount: Optional[Number] = None,
        time_in_force: Optional[TimeInForce] = None,
        self_trade_prevention: Optional[SelfTradePrevention] = None,
        post_only: Optional[bool] = None,
        response_required: Optional[bool] = None,
        operator_id: Optional[int] = None,
    ) -> Order:
        """Amend an open limit or untriggered stop order in place. ``PUT /order`` (weight 1).

        Identify the order by ``order_id`` or ``client_order_id``. Faster than
        cancel + create.
        """
        _require_order_ref(order_id, client_order_id)
        body: Dict[str, Any] = {
            "market": market,
            "orderId": order_id,
            "clientOrderId": client_order_id,
            "operatorId": self._operator(operator_id),
            "amount": _num(amount),
            "amountQuote": _num(amount_quote),
            "amountRemaining": _num(amount_remaining),
            "price": _num(price),
            "triggerAmount": _num(trigger_amount),
            "timeInForce": time_in_force,
            "selfTradePrevention": self_trade_prevention,
            "postOnly": post_only,
            "responseRequired": response_required,
        }
        return cast(Order, self._call("PUT", "/order", body=body, private=True))

    def cancel_order(
        self,
        market: str,
        *,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
        operator_id: Optional[int] = None,
    ) -> CanceledOrder:
        """Cancel one open order. ``DELETE /order`` (weight 1)."""
        _require_order_ref(order_id, client_order_id)
        params = {
            "market": market,
            "orderId": order_id,
            "clientOrderId": client_order_id,
            "operatorId": self._operator(operator_id),
        }
        return cast(CanceledOrder, self._call("DELETE", "/order", params=params, private=True))

    def cancel_orders(
        self, market: Optional[str] = None, *, operator_id: Optional[int] = None
    ) -> List[CanceledOrder]:
        """Cancel all open orders in ``market``, or in every market when omitted.
        ``DELETE /orders`` (weight 25 with market, 100 without).
        """
        params = {"market": market, "operatorId": self._operator(operator_id)}
        return cast(
            List[CanceledOrder],
            self._call(
                "DELETE", "/orders", params=params, private=True, weight=25 if market else 100
            ),
        )

    def atomic_cancel_orders(
        self, market: str, side: Side, *, operator_id: Optional[int] = None
    ) -> List[CanceledOrder]:
        """Cancel all buy or all sell orders in ``market`` as one atomic operation.
        ``DELETE /atomic/orders`` (weight 100).
        """
        body = {"market": market, "side": side, "operatorId": self._operator(operator_id)}
        return cast(
            List[CanceledOrder],
            self._call("DELETE", "/atomic/orders", body=body, private=True, weight=100),
        )

    def cancel_orders_after(
        self, cod_group_id: int, expiry_after_seconds: int
    ) -> CancelOrdersAfter:
        """Arm a dead man's switch: cancel orders in ``cod_group_id`` unless this is
        called again within ``expiry_after_seconds`` (10-300).
        ``POST /cancelOrdersAfter`` (weight 5).
        """
        body = {"codGroupId": cod_group_id, "expiryAfterSeconds": expiry_after_seconds}
        return cast(
            CancelOrdersAfter,
            self._call("POST", "/cancelOrdersAfter", body=body, private=True, weight=5),
        )

    def get_order(
        self,
        market: str,
        *,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
    ) -> Order:
        """One order by ``order_id`` or ``client_order_id``. ``GET /order`` (weight 1).

        Note:
            Bitvavo indexes new orders for this endpoint with a short delay
            (observed 0.2-0.5 s). Querying an order right after creating it can raise
            :class:`~bitvavo_sdk.NotFoundError` (errorCode 240) although the order
            exists. Use :meth:`find_order` when that matters.
        """
        _require_order_ref(order_id, client_order_id)
        params = {"market": market, "orderId": order_id, "clientOrderId": client_order_id}
        return cast(Order, self._call("GET", "/order", params=params, private=True))

    def find_order(
        self,
        market: str,
        *,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
        status: Optional[Collection[str]] = None,
        wait: float = 3.0,
        interval: float = 0.25,
    ) -> Optional[Order]:
        """Look an order up, tolerating Bitvavo's indexing delay.

        ``GET /order`` lags behind order changes: right after a create it can answer
        ``NotFoundError`` (errorCode 240), and right after a cancel it can still show
        the old status. This retries for up to ``wait`` seconds until the order is
        found and, if ``status`` is given, has reached one of those statuses.

        Use it to resolve an unknown outcome (``TransportError`` or errorCode 109)
        before placing an order again, or with ``status={"canceled", "filled"}``
        after a cancel to read the final fill.

        Returns:
            The order (the last version seen if ``status`` was never reached), or
            ``None`` if it was never found. Each attempt costs weight 1.
        """
        deadline = time.monotonic() + wait
        last: Optional[Order] = None
        while True:
            try:
                last = self.get_order(market, order_id=order_id, client_order_id=client_order_id)
                if status is None or last.get("status") in status:
                    return last
            except NotFoundError:
                pass
            if time.monotonic() >= deadline:
                return last
            time.sleep(interval)

    def get_orders(
        self,
        market: str,
        *,
        limit: Optional[int] = None,
        start: Optional[int] = None,
        end: Optional[int] = None,
        order_id_from: Optional[str] = None,
        order_id_to: Optional[str] = None,
    ) -> List[Order]:
        """Order history for a market, newest first. ``GET /orders`` (weight 5)."""
        params = {
            "market": market,
            "limit": limit,
            "start": start,
            "end": end,
            "orderIdFrom": order_id_from,
            "orderIdTo": order_id_to,
        }
        return cast(
            List[Order], self._call("GET", "/orders", params=params, private=True, weight=5)
        )

    def get_open_orders(
        self, market: Optional[str] = None, *, base: Optional[str] = None
    ) -> List[Order]:
        """Open orders, optionally filtered by ``market`` or ``base`` asset.
        ``GET /ordersOpen`` (weight 5 with market, 100 without).
        """
        params = {"market": market, "base": base}
        return cast(
            List[Order],
            self._call(
                "GET", "/ordersOpen", params=params, private=True, weight=5 if market else 100
            ),
        )

    def get_trade_history(
        self,
        market: str,
        *,
        limit: Optional[int] = None,
        start: Optional[int] = None,
        end: Optional[int] = None,
        trade_id_from: Optional[str] = None,
        trade_id_to: Optional[str] = None,
    ) -> List[AccountTrade]:
        """Your own fills in ``market``, newest first, window of at most 24h.
        ``GET /trades`` (weight 5).
        """
        params = {
            "market": market,
            "limit": limit,
            "start": start,
            "end": end,
            "tradeIdFrom": trade_id_from,
            "tradeIdTo": trade_id_to,
        }
        return cast(
            List[AccountTrade], self._call("GET", "/trades", params=params, private=True, weight=5)
        )

    # ------------------------------------------------------------------ account

    def get_account(self) -> Account:
        """Your Category A fee tier and 30-day volume. ``GET /account`` (weight 1)."""
        return cast(Account, self._call("GET", "/account", private=True))

    def get_market_fees(
        self, market: Optional[str] = None, *, quote: Optional[str] = None
    ) -> MarketFees:
        """Your maker/taker fees for a market's fee category.
        ``GET /account/fees`` (weight 1).

        Args:
            quote: ``"EUR"`` or ``"USDC"``.
        """
        params = {"market": market, "quote": quote}
        return cast(MarketFees, self._call("GET", "/account/fees", params=params, private=True))

    def get_balance(self, symbol: Optional[str] = None) -> List[Balance]:
        """Available and in-order balance per asset (non-zero only).
        ``GET /balance`` (weight 5).
        """
        return cast(
            List[Balance],
            self._call("GET", "/balance", params={"symbol": symbol}, private=True, weight=5),
        )

    def get_staking_balance(self, symbol: Optional[str] = None) -> List[StakingBalance]:
        """Assets locked in fixed staking. ``GET /stakingBalance`` (weight 5)."""
        return cast(
            List[StakingBalance],
            self._call("GET", "/stakingBalance", params={"symbol": symbol}, private=True, weight=5),
        )

    def get_transaction_history(
        self,
        *,
        from_date: Optional[int] = None,
        to_date: Optional[int] = None,
        page: Optional[int] = None,
        max_items: Optional[int] = None,
        type: Optional[TransactionType] = None,
    ) -> TransactionHistory:
        """One page of account transactions. ``GET /account/history`` (weight 1).

        See :meth:`iter_transaction_history` to walk every page.
        """
        params = {
            "fromDate": from_date,
            "toDate": to_date,
            "page": page,
            "maxItems": max_items,
            "type": type,
        }
        return cast(
            TransactionHistory, self._call("GET", "/account/history", params=params, private=True)
        )

    def iter_transaction_history(
        self,
        *,
        from_date: Optional[int] = None,
        to_date: Optional[int] = None,
        max_items: int = 100,
        type: Optional[TransactionType] = None,
    ) -> Iterator[Transaction]:
        """Yield every transaction across all pages of ``GET /account/history``."""
        page = 1
        while True:
            params = {
                "fromDate": from_date,
                "toDate": to_date,
                "page": page,
                "maxItems": max_items,
                "type": type,
            }
            result = self._call("GET", "/account/history", params=params, private=True)
            for item in result.get("items", []):  # noqa: UP028 (async twin cannot yield from)
                yield item
            if page >= int(result.get("totalPages", 0)):
                return
            page += 1

    # ----------------------------------------------------------------- transfer

    def get_deposit_data(self, symbol: str) -> DepositData:
        """Deposit address (crypto) or IBAN details (fiat). ``GET /deposit`` (weight 1)."""
        return cast(
            DepositData, self._call("GET", "/deposit", params={"symbol": symbol}, private=True)
        )

    def get_deposit_history(
        self,
        symbol: Optional[str] = None,
        *,
        limit: Optional[int] = None,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> List[TransferRecord]:
        """Past deposits, newest first. ``GET /depositHistory`` (weight 5)."""
        params = {"symbol": symbol, "limit": limit, "start": start, "end": end}
        return cast(
            List[TransferRecord],
            self._call("GET", "/depositHistory", params=params, private=True, weight=5),
        )

    def get_withdrawal_history(
        self,
        symbol: Optional[str] = None,
        *,
        limit: Optional[int] = None,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> List[TransferRecord]:
        """Past withdrawals, newest first. ``GET /withdrawalHistory`` (weight 5)."""
        params = {"symbol": symbol, "limit": limit, "start": start, "end": end}
        return cast(
            List[TransferRecord],
            self._call("GET", "/withdrawalHistory", params=params, private=True, weight=5),
        )

    def withdraw(
        self,
        symbol: str,
        amount: Number,
        address: str,
        *,
        payment_id: Optional[str] = None,
        add_withdrawal_fee: Optional[bool] = None,
    ) -> WithdrawalResult:
        """Withdraw to an address-book address or verified bank account.
        ``POST /withdrawal`` (weight 1).

        Warning:
            API withdrawals skip 2FA and e-mail confirmation.
        """
        body = {
            "symbol": symbol,
            "amount": _num(amount),
            "address": address,
            "paymentId": payment_id,
            "addWithdrawalFee": add_withdrawal_fee,
        }
        return cast(WithdrawalResult, self._call("POST", "/withdrawal", body=body, private=True))

    def withdraw_crypto(
        self,
        asset: str,
        network: str,
        address: str,
        amount: Number,
        *,
        deduct_fee_from_amount: Optional[bool] = None,
        idempotency_key: Optional[str] = None,
        memo: Optional[str] = None,
    ) -> CryptoWithdrawalResult:
        """Withdraw crypto over a specific network. ``POST /crypto/withdrawal`` (weight 25).

        Pass ``idempotency_key`` (5-50 chars) so a retried request cannot pay twice.

        Warning:
            API withdrawals skip 2FA and e-mail confirmation.
        """
        body = {
            "asset": asset,
            "network": network,
            "address": address,
            "amount": _num(amount),
            "deductFeeFromAmount": deduct_fee_from_amount,
            "idempotencyKey": idempotency_key,
            "memo": memo,
        }
        return cast(
            CryptoWithdrawalResult,
            self._call("POST", "/crypto/withdrawal", body=body, private=True, weight=25),
        )


def _require_one(**values: Optional[Number]) -> None:
    given = [k for k, v in values.items() if v is not None]
    if len(given) != 1:
        raise ValueError(f"pass exactly one of {', '.join(values)}")


def _require_order_ref(order_id: Optional[str], client_order_id: Optional[str]) -> None:
    if order_id is None and client_order_id is None:
        raise ValueError("pass order_id or client_order_id")
