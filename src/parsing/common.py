from __future__ import annotations

import io
import re
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

COLUMN_SYNONYMS: Dict[str, List[str]] = {
    "symbol": ["ticker"],
    "quantity": ["qty", "shares", "position"],
    "acquired_date": [
        "purchase_date",
        "open_date",
        "date_acquired",
        "acquired",
    ],
    "cost_basis_total": ["cost_basis", "total_cost", "basis", "cost"],
    "cost_basis_per_share": ["basis_per_share", "cost_per_share"],
    "price": ["last_price", "market_price"],
    "market_value": ["market_value", "value", "position_value"],
    "lot_id": ["lot", "id"],
    "covered": ["is_covered", "covered_flag"],
    "trade_date": ["date", "execution_date"],
    "side": ["action", "buy_sell"],
}


class ParsingError(Exception):
    """Raised when CSV parsing fails."""


class MissingColumnError(ParsingError):
    """Raised when a required column is missing."""


HEADER_PATTERN = re.compile(r"[^a-z0-9]+")


def normalize_header(label: str) -> str:
    return HEADER_PATTERN.sub("_", label.strip().lower()).strip("_")


def normalize_headers(headers: Iterable[str]) -> List[str]:
    return [normalize_header(h) for h in headers]


def build_column_mapping(
    columns: Iterable[str],
    required: Sequence[str],
    optional: Optional[Sequence[str]] = None,
) -> Dict[str, str]:
    normalized = {normalize_header(col): col for col in columns}
    mapping: Dict[str, str] = {}

    def _match(target: str) -> Optional[str]:
        candidates = [target] + COLUMN_SYNONYMS.get(target, [])
        for candidate in candidates:
            norm = normalize_header(candidate)
            if norm in normalized:
                return normalized[norm]
        return None

    for field in required:
        target = _match(field)
        if not target:
            raise MissingColumnError(f"Missing required column for '{field}'")
        mapping[field] = target

    if optional:
        for field in optional:
            target = _match(field)
            if target:
                mapping[field] = target

    return mapping


def rename_columns(df: pd.DataFrame, mapping: Mapping[str, str]) -> pd.DataFrame:
    rename_map = {source: alias for alias, source in mapping.items()}
    return df.rename(columns=rename_map)


def read_csv(source, **kwargs) -> pd.DataFrame:
    if isinstance(source, (str, bytes, io.BytesIO)):
        return pd.read_csv(source, **kwargs)
    if hasattr(source, "read"):
        return pd.read_csv(source, **kwargs)
    raise ParsingError("Unsupported CSV source provided")


def select_and_normalize(
    df: pd.DataFrame,
    required: Sequence[str],
    optional: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    mapping = build_column_mapping(df.columns, required, optional)
    normalized_df = rename_columns(df, mapping)
    return normalized_df[[col for col in mapping]]
