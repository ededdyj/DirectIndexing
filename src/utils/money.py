from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional


def to_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError(f"Cannot convert {value!r} to Decimal") from exc


def safe_float(value: Any, default: Optional[float] = 0.0) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def format_currency(value: Optional[float]) -> str:
    if value is None:
        return "$0.00"
    dec_value = to_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"${dec_value:,.2f}"


def format_pct(value: Optional[float]) -> str:
    if value is None:
        return "0%"
    dec_value = to_decimal(value * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{dec_value}%"
