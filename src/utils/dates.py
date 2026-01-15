from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, Optional

DATE_FORMATS = [
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%d-%b-%Y",
    "%b %d %Y",
]


def parse_date(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if value in (None, ""):
        raise ValueError("Date value is required")
    text = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unsupported date format: {value!r}")


def days_between(a: date, b: date) -> int:
    return abs((b - a).days)


def within_days(target: date, reference: date, days: int) -> bool:
    return days_between(target, reference) <= days


def parse_any_date(values: Iterable) -> Optional[date]:
    for val in values:
        if not val:
            continue
        try:
            return parse_date(val)
        except ValueError:
            continue
    return None
