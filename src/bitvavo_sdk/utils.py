"""Helpers for turning numbers into values Bitvavo accepts.

Bitvavo rejects prices that are not a multiple of the market ``tickSize``
(errorCode 422) and amounts with more decimals than ``quantityDecimals`` /
``notionalDecimals`` (errorCode 429). Use these helpers with the fields from
:meth:`~bitvavo_sdk.Bitvavo.get_markets`.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, Decimal
from typing import Any

from .types import Number

_ROUNDING = {"down": ROUND_DOWN, "up": ROUND_UP, "nearest": ROUND_HALF_UP}


def to_decimal(value: Number) -> Decimal:
    """Convert to :class:`~decimal.Decimal` without binary float artifacts."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def format_number(value: Number) -> str:
    """Format as a plain decimal string: no exponent, no trailing zeros.

    >>> format_number(0.00001)
    '0.00001'
    >>> format_number(Decimal("12.500"))
    '12.5'
    """
    if isinstance(value, bool):
        raise TypeError("booleans are not numbers")
    d = to_decimal(value)
    if not d.is_finite():
        raise ValueError(f"not a finite number: {value!r}")
    text = format(d, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def round_to_tick(price: Number, tick_size: Number, rounding: str = "nearest") -> Decimal:
    """Round ``price`` to a multiple of ``tick_size``.

    Args:
        rounding: ``"nearest"``, ``"down"`` (use for buy limits you must not exceed) or
            ``"up"``.
    """
    tick = to_decimal(tick_size)
    if tick <= 0:
        raise ValueError("tick_size must be positive")
    steps = (to_decimal(price) / tick).quantize(Decimal(1), rounding=_ROUNDING[rounding])
    return (steps * tick).normalize()


def round_to_decimals(amount: Number, decimals: Any, rounding: str = "down") -> Decimal:
    """Truncate/round ``amount`` to ``decimals`` places (``quantityDecimals``).

    Defaults to rounding down so you never try to sell more than you hold.
    ``decimals`` may be an int or a numeric string (Bitvavo sends both).
    """
    exp = Decimal(1).scaleb(-int(decimals))
    return to_decimal(amount).quantize(exp, rounding=_ROUNDING[rounding])
