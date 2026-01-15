from __future__ import annotations

from typing import List

import pandas as pd

from src.models import Holding
from src.utils.money import safe_float

from .common import MissingColumnError, read_csv, select_and_normalize


REQUIRED_COLUMNS = ["symbol", "quantity"]
OPTIONAL_COLUMNS = ["price", "market_value"]


def parse_holdings_csv(source) -> List[Holding]:
    try:
        df = read_csv(source)
    except Exception as exc:  # pragma: no cover - defensive
        raise MissingColumnError(str(exc)) from exc
    normalized = select_and_normalize(df, REQUIRED_COLUMNS, OPTIONAL_COLUMNS)

    holdings: List[Holding] = []
    for _, row in normalized.iterrows():
        qty = safe_float(row.get("quantity"))
        if qty <= 0:
            continue
        holding = Holding(
            symbol=str(row.get("symbol", "")).strip(),
            qty=qty,
            price=_optional_float(row, "price"),
            market_value=_optional_float(row, "market_value"),
        )
        holdings.append(holding)
    return holdings


def _optional_float(row: pd.Series, key: str):
    value = row.get(key)
    return safe_float(value, default=None) if value not in (None, "") else None
