from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

from src.models import StrategySpec, TargetBasketRow
from src.utils.securities import is_money_market_symbol

ROOT = Path(__file__).resolve().parents[2]
UNIVERSE_DIR = ROOT / "data" / "universes"
SCREEN_DIR = ROOT / "data" / "screens"

UNIVERSE_MAP = {
    "sp500": UNIVERSE_DIR / "sp500_universe.csv",
    "total_us": UNIVERSE_DIR / "total_us_universe.csv",
    "nasdaq100": UNIVERSE_DIR / "nasdaq100_universe.csv",
}

SCREEN_FILES = {
    "oil_gas": SCREEN_DIR / "oil_gas_symbols.csv",
    "tobacco": SCREEN_DIR / "tobacco_symbols.csv",
    "weapons": SCREEN_DIR / "weapons_symbols.csv",
}


def load_universe(index_name: str) -> pd.DataFrame:
    path = UNIVERSE_MAP.get(index_name)
    if not path:
        raise ValueError(f"Unknown index name: {index_name}")
    if not path.exists():
        raise FileNotFoundError(f"Universe file missing: {path}")
    df = pd.read_csv(path)
    required = {"symbol", "weight", "sector"}
    if not required.issubset(df.columns):
        raise ValueError(
            f"Universe file must contain columns {sorted(required)}; found {df.columns.tolist()}"
        )
    df = df.copy()
    df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
    df["weight"] = df["weight"].astype(float)
    total = df["weight"].sum()
    if not 0.99 <= total <= 1.01:
        raise ValueError(
            f"Universe file {path.name} weights sum to {total:.4f}, expected approximately 1.0"
        )
    return df


def _load_screen_symbols(name: str) -> List[str]:
    path = SCREEN_FILES.get(name)
    if not path or not path.exists():
        return []
    df = pd.read_csv(path)
    if "symbol" not in df.columns:
        return []
    return df["symbol"].astype(str).str.upper().str.strip().tolist()


def apply_screens(
    df: pd.DataFrame,
    spec: StrategySpec,
    extra_exclusions: Sequence[str] | None = None,
) -> Tuple[pd.DataFrame, List[str]]:
    working = df.copy()
    warnings: List[str] = []
    exclude = set(spec.excluded_symbols or [])
    if extra_exclusions:
        exclude.update(sym.upper().strip() for sym in extra_exclusions if sym)

    for screen_name, enabled in (spec.screens or {}).items():
        if not enabled:
            continue
        symbols = _load_screen_symbols(screen_name)
        if not symbols:
            warnings.append(f"Screen list '{screen_name}' is empty or missing")
        exclude.update(symbols)

    if exclude:
        working = working[~working["symbol"].isin(exclude)]
    return working, warnings


def cap_and_renormalize(df: pd.DataFrame, max_weight: float) -> pd.DataFrame:
    working = df.copy()
    total = working["weight"].sum()
    if total <= 0:
        return working
    working["weight"] = working["weight"] / total
    if max_weight <= 0 or max_weight >= 1:
        return working

    for _ in range(10):
        over_mask = working["weight"] > max_weight + 1e-9
        if not over_mask.any():
            break
        excess = (working.loc[over_mask, "weight"] - max_weight).sum()
        working.loc[over_mask, "weight"] = max_weight
        remaining_mask = ~over_mask
        remaining_total = working.loc[remaining_mask, "weight"].sum()
        if remaining_total <= 0:
            break
        working.loc[remaining_mask, "weight"] += (
            working.loc[remaining_mask, "weight"] / remaining_total
        ) * excess

    working["weight"] = working["weight"] / working["weight"].sum()
    return working


def limit_to_top_n(df: pd.DataFrame, n: int) -> pd.DataFrame:
    working = df.sort_values("weight", ascending=False)
    if n > 0:
        working = working.head(n)
    total = working["weight"].sum()
    if total > 0:
        working["weight"] = working["weight"] / total
    return working


def build_target_basket(
    universe_df: pd.DataFrame,
    spec: StrategySpec,
    sector_map: Optional[Dict[str, str]] = None,
    extra_exclusions: Sequence[str] | None = None,
) -> Tuple[pd.DataFrame, List[str]]:
    working = universe_df.copy()
    warnings: List[str] = []

    working, screen_warnings = apply_screens(working, spec, extra_exclusions)
    warnings.extend(screen_warnings)

    if not spec.include_cash_equivalents:
        before = len(working)
        working = working[~working["symbol"].apply(is_money_market_symbol)]
        if len(working) < before:
            warnings.append("Cash/money-market symbols removed from target basket")

    if working.empty:
        warnings.append("All symbols removed after applying screens/exclusions.")
        return working, warnings

    working = cap_and_renormalize(working, spec.max_single_name_weight)
    working = limit_to_top_n(working, spec.holdings_count)
    working = cap_and_renormalize(working, spec.max_single_name_weight)
    working = working.reset_index(drop=True)

    if working.empty:
        warnings.append("No holdings remain after limiting to requested count.")
        return working, warnings

    if "sector" not in working.columns:
        working["sector"] = None
    if sector_map:
        working["sector"] = working["sector"].fillna(
            working["symbol"].map({k.upper(): v for k, v in sector_map.items()})
        )

    total = working["weight"].sum()
    if not 0.99 <= total <= 1.01 and total > 0:
        working["weight"] = working["weight"] / total
        warnings.append("Weights renormalized after filtering.")

    if len(working) < spec.holdings_count:
        warnings.append(
            "Fewer holdings available than requested count after screens/exclusions."
        )

    return working, warnings


def basket_to_rows(df: pd.DataFrame, index_name: str) -> List[TargetBasketRow]:
    rows: List[TargetBasketRow] = []
    for _, row in df.iterrows():
        rows.append(
            TargetBasketRow(
                symbol=row["symbol"],
                target_weight=float(row["weight"]),
                sector=row.get("sector"),
                source_index=index_name,
            )
        )
    return rows


def export_basket_csv(df: pd.DataFrame) -> str:
    from io import StringIO

    buffer = StringIO()
    df.to_csv(buffer, index=False)
    return buffer.getvalue()
