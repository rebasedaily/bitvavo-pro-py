from __future__ import annotations

import asyncio
import inspect
import json
import subprocess
import sys
from pathlib import Path

import httpx

from bitvavo_sdk import AsyncBitvavo, Bitvavo, ServerError

from .conftest import KEY, SECRET

ROOT = Path(__file__).resolve().parent.parent


def test_async_client_mirrors_sync_api():
    def public(cls):
        return {n for n, _ in inspect.getmembers(cls, inspect.isfunction) if not n.startswith("_")}

    assert public(Bitvavo) - {"close"} == public(AsyncBitvavo) - {"close"}
    assert inspect.iscoroutinefunction(AsyncBitvavo.get_markets)
    assert inspect.isasyncgenfunction(AsyncBitvavo.iter_transaction_history)


def test_generated_async_code_is_up_to_date():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_async.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout


def test_async_order_and_retry(mock_api):
    order = mock_api.post("/order").mock(
        side_effect=[
            httpx.Response(503, json={"errorCode": 111, "error": "engine"}),
            httpx.Response(200, json={"orderId": "1"}),
        ]
    )
    mock_api.get("/time").respond(503, json={"errorCode": 400, "error": "x"})

    async def main():
        async with AsyncBitvavo(KEY, SECRET, operator_id=5, retry_backoff=0, max_retries=1) as c:
            placed = await c.limit_sell("BTC-EUR", "0.5", 70000)
            try:
                await c.get_time()
            except ServerError as e:
                return placed, e
        raise AssertionError("expected ServerError")

    placed, err = asyncio.run(main())
    assert placed == {"orderId": "1"}
    assert err.error_code == 400
    assert order.call_count == 2
    sent = json.loads(order.calls.last.request.content)
    assert sent["operatorId"] == 5 and sent["price"] == "70000" and sent["side"] == "sell"


def test_async_pagination(mock_api):
    mock_api.get("/account/history").respond(
        json={"items": [{"transactionId": "x"}], "currentPage": 1, "totalPages": 1, "maxItems": 100}
    )

    async def main():
        async with AsyncBitvavo(KEY, SECRET) as c:
            return [t async for t in c.iter_transaction_history()]

    assert asyncio.run(main()) == [{"transactionId": "x"}]


def test_async_find_order_uses_asyncio_sleep(mock_api, monkeypatch):
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr("bitvavo_sdk._async_endpoints.asyncio.sleep", fake_sleep)
    mock_api.get("/order").mock(
        side_effect=[
            httpx.Response(404, json={"errorCode": 240, "error": "not yet"}),
            httpx.Response(200, json={"orderId": "1"}),
        ]
    )

    async def main():
        async with AsyncBitvavo(KEY, SECRET) as c:
            return await c.find_order("BTC-EUR", order_id="1")

    assert asyncio.run(main()) == {"orderId": "1"}
    assert slept == [0.25]
