from __future__ import annotations

from typing import Iterable, Set


DEFAULT_MONEY_MARKET_TICKERS: Set[str] = {
    "VMFXX",  # Vanguard Federal Money Market Fund
    "SPRXX",  # Fidelity Money Market
    "SPAXX",
    "SWVXX",
    "FDLXX",
    "SNVXX",
    "VMMXX",
    "FZFXX",
}


def is_money_market_symbol(symbol: str, overrides: Iterable[str] | None = None) -> bool:
    if not symbol:
        return False
    symbol_upper = symbol.strip().upper()
    custom = {s.strip().upper() for s in overrides or []}
    return symbol_upper in (DEFAULT_MONEY_MARKET_TICKERS | custom)
