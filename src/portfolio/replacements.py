from __future__ import annotations

from typing import Dict, Iterable, List, Optional

import pandas as pd

from src.models import ReplacementBasket
from src.parsing.common import read_csv, select_and_normalize

SECTOR_PROXIES: Dict[str, List[str]] = {
    "Technology": ["XLK", "VGT", "QQQ"],
    "Financials": ["XLF", "VFH", "KBE"],
    "Healthcare": ["XLV", "VHT", "IHE"],
    "Consumer_Discretionary": ["XLY", "VCR", "FDIS"],
    "Industrials": ["XLI", "VIS", "IYJ"],
}

GENERIC_PROXIES = ["SPY", "VTI", "SCHB", "IVV"]


def load_sector_map(source) -> Dict[str, str]:
    try:
        df = read_csv(source)
    except FileNotFoundError:
        return {}
    normalized = select_and_normalize(df, ["symbol", "sector"], [])
    return {row.symbol.upper(): row.sector for row in normalized.itertuples()}


def infer_sector(symbol: str, sector_map: Optional[Dict[str, str]] = None) -> Optional[str]:
    if not sector_map:
        return None
    return sector_map.get(symbol.upper())


def build_replacement_basket(
    symbol: str,
    sector: Optional[str] = None,
    target_value: float = 0.0,
) -> List[ReplacementBasket]:
    tickers = GENERIC_PROXIES
    if sector:
        normalized_sector = sector.replace(" ", "_")
        tickers = SECTOR_PROXIES.get(normalized_sector, tickers)
    weight = 1 / len(tickers)
    return [ReplacementBasket(symbol=t, weight=weight) for t in tickers]
