from __future__ import annotations

from typing import List

from src.models import Trade
from src.utils.dates import parse_date
from src.utils.money import safe_float

from .common import read_csv, select_and_normalize

REQUIRED_COLUMNS = ["symbol", "trade_date", "quantity", "side"]
OPTIONAL_COLUMNS = []


def parse_trades_csv(source) -> List[Trade]:
    df = read_csv(source)
    normalized = select_and_normalize(df, REQUIRED_COLUMNS, OPTIONAL_COLUMNS)
    trades: List[Trade] = []
    for _, row in normalized.iterrows():
        qty = safe_float(row.get("quantity"))
        if not qty:
            continue
        trade = Trade(
            symbol=str(row.get("symbol", "")).strip(),
            side=str(row.get("side", "")).strip().upper(),
            trade_date=parse_date(row.get("trade_date")),
            qty=abs(qty),
        )
        trades.append(trade)
    return trades
