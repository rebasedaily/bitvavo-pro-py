from __future__ import annotations

import json
import time

import httpx
import pytest

from bitvavo_sdk import (
    AuthenticationError,
    Bitvavo,
    InsufficientBalanceError,
    MarketNotTradingError,
    MissingCredentialsError,
    NotFoundError,
    RateLimitError,
    ServerError,
    TransportError,
    create_signature,
)

from .conftest import KEY, SECRET


def _check_signature(request: httpx.Request) -> None:
    raw_path = request.url.raw_path.decode()
    expected = create_signature(
        SECRET,
        int(request.headers["Bitvavo-Access-Timestamp"]),
        request.method,
        raw_path,
        request.content.decode(),
    )
    assert request.headers["Bitvavo-Access-Signature"] == expected
    assert request.headers["Bitvavo-Access-Key"] == KEY


# -- signing & request shape ------------------------------------------------------


def test_public_request_without_credentials_is_unsigned(mock_api, public_client):
    route = mock_api.get("/time").respond(json={"time": 1, "timeNs": 1})
    assert public_client.get_time() == {"time": 1, "timeNs": 1}
    req = route.calls.last.request
    assert "Bitvavo-Access-Key" not in req.headers
    assert req.headers["User-Agent"].startswith("bitvavo-sdk-python/")


def test_signed_get_includes_query_string(mock_api, client):
    route = mock_api.get("/order").respond(json={"orderId": "abc"})
    client.get_order("BTC-EUR", order_id="abc")
    req = route.calls.last.request
    assert req.url.raw_path == b"/v2/order?market=BTC-EUR&orderId=abc"
    assert req.content == b""
    _check_signature(req)


def test_create_order_body(mock_api, client):
    route = mock_api.post("/order").respond(json={"orderId": "1"})
    client.create_order("BTC-EUR", "buy", "limit", amount=0.00001, price="50000.10", post_only=True)
    req = route.calls.last.request
    assert json.loads(req.content) == {
        "market": "BTC-EUR",
        "side": "buy",
        "orderType": "limit",
        "operatorId": 42,
        "amount": "0.00001",
        "price": "50000.1",
        "postOnly": True,
    }
    assert b" " not in req.content  # compact JSON, identical to what was signed
    assert req.headers["Content-Type"] == "application/json"
    _check_signature(req)


def test_operator_id_per_call_override(mock_api, client):
    route = mock_api.delete("/orders").respond(json=[])
    client.cancel_orders("BTC-EUR", operator_id=7)
    assert route.calls.last.request.url.params["operatorId"] == "7"


def test_operator_id_required():
    c = Bitvavo(KEY, SECRET)
    with pytest.raises(ValueError, match="operatorId"):
        c.market_buy("BTC-EUR", amount_quote=10)


def test_market_buy_needs_exactly_one_amount(client):
    with pytest.raises(ValueError):
        client.market_buy("BTC-EUR")
    with pytest.raises(ValueError):
        client.market_buy("BTC-EUR", amount=1, amount_quote=1)


def test_private_endpoint_without_credentials(mock_api, public_client):
    route = mock_api.get("/balance")
    with pytest.raises(MissingCredentialsError):
        public_client.get_balance()
    assert not route.called


def test_constructor_validation():
    with pytest.raises(ValueError):
        Bitvavo(KEY)
    with pytest.raises(ValueError):
        Bitvavo(access_window_ms=70_000)


def test_from_env(monkeypatch):
    monkeypatch.setenv("BITVAVO_API_KEY", KEY)
    monkeypatch.setenv("BITVAVO_API_SECRET", SECRET)
    monkeypatch.setenv("BITVAVO_OPERATOR_ID", "99")
    c = Bitvavo.from_env()
    assert c.has_credentials and c.operator_id == 99
    assert SECRET not in repr(c)


def test_single_market_endpoints_unwrap_lists(mock_api, public_client):
    mock_api.get("/markets").respond(json=[{"market": "BTC-EUR"}])
    assert public_client.get_market("BTC-EUR") == {"market": "BTC-EUR"}
    mock_api.get("/ticker/price").respond(json={"market": "BTC-EUR", "price": "1"})
    assert public_client.get_ticker_price("BTC-EUR")["price"] == "1"


def test_iter_transaction_history_walks_pages(mock_api, client):
    pages = {
        "1": {"items": [{"transactionId": "a"}], "currentPage": 1, "totalPages": 2, "maxItems": 1},
        "2": {"items": [{"transactionId": "b"}], "currentPage": 2, "totalPages": 2, "maxItems": 1},
    }
    mock_api.get("/account/history").mock(
        side_effect=lambda req: httpx.Response(200, json=pages[req.url.params["page"]])
    )
    ids = [t["transactionId"] for t in client.iter_transaction_history(max_items=1)]
    assert ids == ["a", "b"]


# -- errors -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "code", "exc"),
    [
        (403, 309, AuthenticationError),
        (400, 216, InsufficientBalanceError),
        (404, 240, NotFoundError),
        (409, 431, MarketNotTradingError),
        (400, 425, MarketNotTradingError),
    ],
)
def test_error_mapping(mock_api, client, status, code, exc):
    mock_api.post("/order").respond(status, json={"errorCode": code, "error": "boom"})
    with pytest.raises(exc) as info:
        client.market_buy("BTC-EUR", amount_quote=10)
    assert info.value.error_code == code
    assert info.value.status_code == status
    assert "boom" in str(info.value)


def test_rate_limit_error_carries_reset(mock_api, client):
    mock_api.get("/balance").respond(
        429,
        json={"errorCode": 105, "error": "limited"},
        headers={"bitvavo-ratelimit-remaining": "0", "bitvavo-ratelimit-resetat": "1700000060000"},
    )
    with pytest.raises(RateLimitError) as info:
        client.get_balance()
    assert info.value.reset_at == 1700000060000


def test_non_json_error_body(mock_api, public_client):
    mock_api.get("/time").respond(502, text="<html>bad gateway</html>")
    public_client.max_retries = 0
    with pytest.raises(ServerError) as info:
        public_client.get_time()
    assert info.value.error_code is None


# -- retries --------------------------------------------------------------------------


def test_get_retries_on_5xx(mock_api, public_client):
    route = mock_api.get("/time").mock(
        side_effect=[
            httpx.Response(503, json={"errorCode": 419, "error": "unavailable"}),
            httpx.Response(200, json={"time": 1, "timeNs": 1}),
        ]
    )
    assert public_client.get_time()["time"] == 1
    assert route.call_count == 2


def test_order_not_retried_on_ambiguous_timeout(mock_api, client):
    route = mock_api.post("/order").respond(503, json={"errorCode": 109, "error": "timeout"})
    with pytest.raises(ServerError):
        client.market_buy("BTC-EUR", amount_quote=10)
    assert route.call_count == 1


def test_order_retried_when_bitvavo_says_not_processed(mock_api, client):
    route = mock_api.post("/order").mock(
        side_effect=[
            httpx.Response(503, json={"errorCode": 107, "error": "overloaded"}),
            httpx.Response(200, json={"orderId": "1"}),
        ]
    )
    assert client.market_buy("BTC-EUR", amount_quote=10)["orderId"] == "1"
    assert route.call_count == 2


def test_order_transport_error_not_retried(mock_api, client):
    route = mock_api.post("/order").mock(side_effect=httpx.ConnectTimeout("slow"))
    with pytest.raises(TransportError):
        client.market_buy("BTC-EUR", amount_quote=10)
    assert route.call_count == 1


def test_get_transport_error_retried_then_raised(mock_api, public_client):
    route = mock_api.get("/time").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(TransportError):
        public_client.get_time()
    assert route.call_count == 3


def test_clock_skew_triggers_time_sync_and_retry(mock_api, client, monkeypatch):
    server_ms = int(time.time() * 1000) + 30_000
    mock_api.get("/time").respond(json={"time": server_ms, "timeNs": 0})
    route = mock_api.get("/balance").mock(
        side_effect=[
            httpx.Response(403, json={"errorCode": 304, "error": "window"}),
            httpx.Response(200, json=[]),
        ]
    )
    assert client.get_balance() == []
    assert route.call_count == 2
    assert 29_000 < client.time_offset_ms < 31_000
    second_ts = int(route.calls[1].request.headers["Bitvavo-Access-Timestamp"])
    assert abs(second_ts - server_ms) < 1_000


# -- rate limiting ---------------------------------------------------------------------


def test_rate_limit_headers_tracked(mock_api, public_client):
    mock_api.get("/time").respond(
        json={"time": 1, "timeNs": 1},
        headers={
            "bitvavo-ratelimit-limit": "1000",
            "bitvavo-ratelimit-remaining": "995",
            "bitvavo-ratelimit-resetat": "1700000000000",
        },
    )
    public_client.get_time()
    rl = public_client.rate_limit
    assert (rl.limit, rl.remaining, rl.reset_at) == (1000, 995, 1700000000000)


def test_waits_when_budget_is_low(mock_api, public_client, monkeypatch):
    slept = []
    monkeypatch.setattr("bitvavo_sdk.client.time.sleep", slept.append)
    mock_api.get("/ticker/24h").respond(json=[])
    public_client.rate_limit.remaining = 30
    public_client.rate_limit.reset_at = int(time.time() * 1000) + 2_000
    public_client.get_tickers_24h()  # weight 25, buffer 20 -> must wait
    assert len(slept) == 1 and 1.0 < slept[0] <= 2.0


def test_no_wait_when_disabled(mock_api, monkeypatch):
    slept = []
    monkeypatch.setattr("bitvavo_sdk.client.time.sleep", slept.append)
    mock_api.get("/ticker/24h").respond(json=[])
    c = Bitvavo(wait_on_rate_limit=False)
    c.rate_limit.remaining = 0
    c.rate_limit.reset_at = int(time.time() * 1000) + 2_000
    c.get_tickers_24h()
    assert slept == []


def test_raw_request_escape_hatch(mock_api, client):
    route = mock_api.get("/someNewEndpoint").respond(json={"ok": True})
    assert client.request("GET", "/someNewEndpoint", params={"a": 1}, private=True) == {"ok": True}
    _check_signature(route.calls.last.request)


def test_rate_limit_error_makes_next_call_wait(mock_api, client, monkeypatch):
    slept = []
    monkeypatch.setattr("bitvavo_sdk.client.time.sleep", slept.append)
    reset = int(time.time() * 1000) + 3_000
    mock_api.get("/balance").mock(
        side_effect=[
            httpx.Response(
                429,
                json={"errorCode": 105, "error": "limited"},
                headers={"bitvavo-ratelimit-resetat": str(reset)},
            ),
            httpx.Response(200, json=[]),
        ]
    )
    with pytest.raises(RateLimitError):
        client.get_balance()
    assert client.get_balance() == []
    assert len(slept) == 1 and 2.0 < slept[0] <= 3.0


def test_find_order_waits_out_indexing_delay(mock_api, client, monkeypatch):
    monkeypatch.setattr("bitvavo_sdk._endpoints.time.sleep", lambda s: None)
    not_found = httpx.Response(404, json={"errorCode": 240, "error": "No active order found."})
    route = mock_api.get("/order").mock(
        side_effect=[not_found, not_found, httpx.Response(200, json={"orderId": "1"})]
    )
    assert client.find_order("BTC-EUR", client_order_id="c") == {"orderId": "1"}
    assert route.call_count == 3


def test_find_order_waits_for_status(mock_api, client, monkeypatch):
    monkeypatch.setattr("bitvavo_sdk._endpoints.time.sleep", lambda s: None)
    route = mock_api.get("/order").mock(
        side_effect=[
            httpx.Response(200, json={"orderId": "1", "status": "new"}),
            httpx.Response(200, json={"orderId": "1", "status": "canceled"}),
        ]
    )
    found = client.find_order("BTC-EUR", order_id="1", status={"canceled", "filled"})
    assert found["status"] == "canceled" and route.call_count == 2


def test_find_order_returns_last_seen_when_status_not_reached(mock_api, client, monkeypatch):
    monkeypatch.setattr("bitvavo_sdk._endpoints.time.sleep", lambda s: None)
    mock_api.get("/order").respond(json={"orderId": "1", "status": "new"})
    found = client.find_order("BTC-EUR", order_id="1", status={"canceled"}, wait=0)
    assert found == {"orderId": "1", "status": "new"}


def test_find_order_returns_none_after_wait(mock_api, client, monkeypatch):
    monkeypatch.setattr("bitvavo_sdk._endpoints.time.sleep", lambda s: None)
    mock_api.get("/order").respond(404, json={"errorCode": 240, "error": "No active order found."})
    assert client.find_order("BTC-EUR", order_id="x", wait=0) is None
