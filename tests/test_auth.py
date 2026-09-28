from bitvavo_sdk import create_signature
from bitvavo_sdk.auth import auth_headers


def test_signature_matches_bitvavo_documentation_example():
    # Vector from https://docs.bitvavo.com/docs/rest-api/introduction/
    body = '{"market":"BTC-EUR","side":"buy","price":"5000","amount":"1.23","orderType":"limit"}'
    sig = create_signature("bitvavo", 1548172481125, "POST", "/v2/order", body)
    assert sig == "44d022723a20973a18f7ee97398b9fdd405d2d019c8d39e24b8cc0dcb39ca016"


def test_method_is_uppercased():
    assert create_signature("x", 1, "get", "/v2/time") == create_signature(
        "x", 1, "GET", "/v2/time"
    )


def test_auth_headers():
    h = auth_headers("key", "secret", 123, "GET", "/v2/balance", access_window_ms=5000)
    assert h["Bitvavo-Access-Key"] == "key"
    assert h["Bitvavo-Access-Timestamp"] == "123"
    assert h["Bitvavo-Access-Window"] == "5000"
    assert h["Bitvavo-Access-Signature"] == create_signature("secret", 123, "GET", "/v2/balance")
