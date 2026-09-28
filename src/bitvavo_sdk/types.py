"""Typed shapes of Bitvavo REST API requests and responses.

Responses are returned as plain ``dict``/``list`` objects exactly as Bitvavo sends
them; the ``TypedDict`` classes below only describe their shape so editors and
type checkers can help you. Monetary values are strings on the wire; convert them
with :class:`decimal.Decimal`, never ``float``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import List, Literal, TypedDict, Union

#: Any value accepted where Bitvavo expects a decimal number. Converted to a plain
#: decimal string (never scientific notation) before it is sent.
Number = Union[str, int, float, Decimal]

Side = Literal["buy", "sell"]
OrderType = Literal["market", "limit", "stopLoss", "stopLossLimit", "takeProfit", "takeProfitLimit"]
TimeInForce = Literal["GTC", "IOC", "FOK"]
SelfTradePrevention = Literal["decrementAndCancel", "cancelOldest", "cancelNewest", "cancelBoth"]
TriggerType = Literal["price"]
TriggerReference = Literal["lastTrade", "bestBid", "bestAsk", "midPrice"]
MarketStatus = Literal["trading", "halted", "auction", "auctionMatching", "cancelOnly"]
OrderStatus = Literal["new", "awaitingTrigger", "canceled", "expired", "filled", "partiallyFilled"]
CandleInterval = Literal[
    "1m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "1W", "1M"
]
TransactionType = Literal[
    "sell",
    "buy",
    "staking",
    "fixed_staking",
    "deposit",
    "withdrawal",
    "affiliate",
    "distribution",
    "internal_transfer",
    "withdrawal_cancelled",
    "rebate",
    "loan",
    "external_transferred_funds",
    "manually_assigned",
]


class ServerTime(TypedDict):
    time: int
    timeNs: int


class Market(TypedDict, total=False):
    market: str
    status: MarketStatus
    base: str
    quote: str
    pricePrecision: int  # deprecated by Bitvavo, use tickSize
    minOrderInBaseAsset: str
    minOrderInQuoteAsset: str
    maxOrderInBaseAsset: str
    maxOrderInQuoteAsset: str
    orderTypes: List[OrderType]
    quantityDecimals: int
    notionalDecimals: int
    tickSize: str
    maxOpenOrders: int
    feeCategory: str


class Asset(TypedDict, total=False):
    symbol: str
    name: str
    decimals: int
    depositFee: str
    depositConfirmations: int
    depositStatus: str
    withdrawalFee: str
    withdrawalMinAmount: str
    withdrawalStatus: str
    networks: List[str]
    message: str


class OrderBook(TypedDict):
    market: str
    nonce: int
    #: ``[price, amount]`` pairs, best first.
    bids: List[List[str]]
    asks: List[List[str]]
    timestamp: int


class PublicTrade(TypedDict):
    id: str
    timestamp: int
    amount: str
    price: str
    side: Side


#: ``[timestamp, open, high, low, close, volume]``
Candle = List[Union[int, str]]


class TickerPrice(TypedDict):
    market: str
    price: str


class TickerBook(TypedDict, total=False):
    market: str
    bid: str
    bidSize: str
    ask: str
    askSize: str


class Ticker24h(TypedDict, total=False):
    market: str
    startTimestamp: int
    timestamp: int
    open: str
    openTimestamp: int
    high: str
    low: str
    last: str
    closeTimestamp: int
    bid: str
    bidSize: str
    ask: str
    askSize: str
    volume: str
    volumeQuote: str


class Fill(TypedDict, total=False):
    id: str
    timestamp: int
    amount: str
    price: str
    taker: bool
    fee: str
    feeCurrency: str
    settled: bool


class Order(TypedDict, total=False):
    orderId: str
    clientOrderId: str
    market: str
    created: int
    updated: int
    createdNs: int
    updatedNs: int
    status: OrderStatus
    side: Side
    orderType: OrderType
    amount: str
    amountRemaining: str
    price: str
    amountQuote: str
    amountQuoteRemaining: str
    onHold: str
    onHoldCurrency: str
    triggerPrice: str
    triggerAmount: str
    triggerType: TriggerType
    triggerReference: TriggerReference
    filledAmount: str
    filledAmountQuote: str
    feePaid: str
    feeCurrency: str
    fills: List[Fill]
    selfTradePrevention: SelfTradePrevention
    visible: bool
    timeInForce: TimeInForce
    postOnly: bool
    operatorId: int
    restatementReason: str
    codGroupId: int


class CanceledOrder(TypedDict, total=False):
    orderId: str
    clientOrderId: str
    operatorId: int


class CancelOrdersAfter(TypedDict):
    codGroupId: int
    timeOfExpirySeconds: int


class AccountTrade(TypedDict, total=False):
    id: str
    orderId: str
    clientOrderId: str
    operatorId: int
    timestamp: int
    market: str
    side: Side
    amount: str
    price: str
    taker: bool
    fee: str
    feeCurrency: str
    settled: bool


class FeeTier(TypedDict):
    taker: str
    maker: str
    volume: str


class Account(TypedDict):
    fees: FeeTier


class MarketFees(TypedDict):
    tier: str
    volume: str
    taker: str
    maker: str


class Balance(TypedDict):
    symbol: str
    available: str
    inOrder: str


class StakingBalance(TypedDict):
    symbol: str
    amount: str


class Transaction(TypedDict, total=False):
    transactionId: str
    executedAt: str
    type: TransactionType
    priceCurrency: str
    priceAmount: str
    sentCurrency: str
    sentAmount: str
    receivedCurrency: str
    receivedAmount: str
    feesCurrency: str
    feesAmount: str
    address: str


class TransactionHistory(TypedDict):
    items: List[Transaction]
    currentPage: int
    totalPages: int
    maxItems: int


class DepositData(TypedDict, total=False):
    address: str
    paymentid: str
    iban: str
    bic: str
    description: str


class TransferRecord(TypedDict, total=False):
    timestamp: int
    symbol: str
    amount: str
    address: str
    paymentId: str
    txId: str
    fee: str
    status: str


class WithdrawalResult(TypedDict):
    success: bool
    symbol: str
    amount: str


class CryptoWithdrawalResult(TypedDict, total=False):
    id: str
    asset: str
    network: str
    address: str
    amount: str
    fee: str
    createdAt: str
