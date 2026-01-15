from __future__ import annotations

from typing import List

import pandas as pd

from src.models import Lot
from src.utils.dates import parse_date
from src.utils.money import safe_float

from .common import MissingColumnError, read_csv, select_and_normalize

REQUIRED_COLUMNS = ["symbol", "acquired_date", "quantity"]
OPTIONAL_COLUMNS = [
    "cost_basis_total",
    "cost_basis_per_share",
    "lot_id",
    "covered",
]


def parse_lots_csv(source) -> List[Lot]:
    df = read_csv(source)
    normalized = select_and_normalize(df, REQUIRED_COLUMNS, OPTIONAL_COLUMNS)

    lots: List[Lot] = []
    for idx, row in normalized.iterrows():
        qty = safe_float(row.get("quantity"))
        if not qty or qty <= 0:
            continue
        acquired_date = parse_date(row.get("acquired_date"))
        basis_total = _derive_basis(row, qty)
        lot_id = row.get("lot_id") or f"{row['symbol']}_{acquired_date.isoformat()}_{idx}"
        covered = _parse_bool(row.get("covered"))
        lot = Lot(
            lot_id=str(lot_id),
            symbol=str(row.get("symbol", "")).strip(),
            acquired_date=acquired_date,
            qty=qty,
            basis_total=basis_total,
            covered=covered,
        )
        lots.append(lot)
    return lots


def _derive_basis(row: pd.Series, qty: float) -> float:
    total = row.get("cost_basis_total")
    per_share = row.get("cost_basis_per_share")
    total_val = safe_float(total)
    per_val = safe_float(per_share)
    if total_val is not None and total_val > 0:
        return total_val
    if per_val is not None and per_val > 0:
        return per_val * qty
    raise MissingColumnError("Missing cost basis for lot")


def _parse_bool(value):
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"y", "yes", "true", "1"}:
        return True
    if text in {"n", "no", "false", "0"}:
        return False
    return None
