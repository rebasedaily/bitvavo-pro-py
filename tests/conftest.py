from __future__ import annotations

import pytest
import respx

from bitvavo_sdk import Bitvavo

BASE = "https://api.bitvavo.com/v2"
KEY = "k" * 64
SECRET = "s" * 128


@pytest.fixture
def mock_api():
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        yield router


@pytest.fixture
def client():
    with Bitvavo(KEY, SECRET, operator_id=42, retry_backoff=0) as c:
        yield c


@pytest.fixture
def public_client():
    with Bitvavo(retry_backoff=0) as c:
        yield c
