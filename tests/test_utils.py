from decimal import Decimal

import pytest

from bitvavo_sdk import format_number, round_to_decimals, round_to_tick


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.00001, "0.00001"),
        (1e-8, "0.00000001"),
        (Decimal("12.500"), "12.5"),
        (Decimal("1E+3"), "1000"),
        (10, "10"),
        ("0.10", "0.1"),
        (0.1 + 0.2, "0.30000000000000004"),
        (Decimal("-0"), "0"),
    ],
)
def test_format_number(value, expected):
    assert format_number(value) == expected


def test_format_number_rejects_bool_and_nan():
    with pytest.raises(TypeError):
        format_number(True)
    with pytest.raises(ValueError):
        format_number(Decimal("NaN"))


def test_round_to_tick():
    assert round_to_tick("72715.6", "1.00") == Decimal("72716")
    assert round_to_tick("0.123456", "0.0001", "down") == Decimal("0.1234")
    assert round_to_tick("0.123401", "0.0001", "up") == Decimal("0.1235")
    assert round_to_tick("5", "0.5") == Decimal("5")


def test_round_to_decimals_accepts_string_decimals():
    assert round_to_decimals("1.23456789", "4") == Decimal("1.2345")
    assert round_to_decimals(Decimal("1.99999"), 2) == Decimal("1.99")
