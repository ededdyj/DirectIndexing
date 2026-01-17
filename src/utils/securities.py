from __future__ import annotations

import re
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

EQUITY_SYMBOL_PATTERN = re.compile(r"^[A-Z]{1,5}(?:\.[A-Z]{1,2})?$")
SYMBOL_TOKEN_PATTERN = re.compile(r"^[A-Z0-9]{1,8}(?:\.[A-Z0-9]{1,4})?$")


def is_money_market_symbol(symbol: str, overrides: Iterable[str] | None = None) -> bool:
    if not symbol:
        return False
    symbol_upper = symbol.strip().upper()
    custom = {s.strip().upper() for s in overrides or []}
    return symbol_upper in (DEFAULT_MONEY_MARKET_TICKERS | custom)


def is_equity_symbol(symbol: str) -> bool:
    if not symbol:
        return False
    return bool(EQUITY_SYMBOL_PATTERN.fullmatch(symbol.strip().upper()))


def looks_like_symbol(symbol: str) -> bool:
    if not symbol:
        return False
    return bool(SYMBOL_TOKEN_PATTERN.fullmatch(symbol.strip().upper()))
