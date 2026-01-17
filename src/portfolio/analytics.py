from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Tuple

from src.models import Holding, Lot


def holding_market_value(holding: Holding) -> float:
    if holding.market_value is not None:
        return holding.market_value
    if holding.price is not None:
        return holding.price * holding.qty
    return 0.0


def price_lookup(holdings: List[Holding]) -> Dict[str, float]:
    lookup: Dict[str, float] = {}
    for holding in holdings:
        if getattr(holding, "is_cash_equivalent", False):
            continue
        if holding.price is not None and holding.price > 0:
            lookup[holding.symbol] = holding.price
        elif holding.market_value is not None and holding.qty:
            lookup[holding.symbol] = holding.market_value / holding.qty
    return lookup


def compare_holdings_to_lots(
    holdings: List[Holding],
    lots: List[Lot],
    tolerance: float = 0.01,
    exclude_symbols: Optional[Iterable[str]] = None,
) -> List[Tuple[str, float]]:
    holding_qty = defaultdict(float)
    lot_qty = defaultdict(float)
    exclude = {s.strip().upper() for s in (exclude_symbols or []) if s}
    for h in holdings:
        if h.symbol.upper() in exclude:
            continue
        holding_qty[h.symbol] += h.qty
    for lot in lots:
        if lot.symbol.upper() in exclude:
            continue
        lot_qty[lot.symbol] += lot.qty

    mismatches = []
    symbols = set(holding_qty.keys()) | set(lot_qty.keys())
    for symbol in symbols:
        diff = holding_qty[symbol] - lot_qty[symbol]
        if abs(diff) > tolerance:
            mismatches.append((symbol, diff))
    return mismatches


def find_lots_missing_basis(lots: List[Lot]) -> List[str]:
    missing = []
    for lot in lots:
        if lot.basis_total <= 0:
            missing.append(lot.lot_id)
    return missing


def run_health_checks(holdings: List[Holding], lots: List[Lot]) -> Dict[str, List[str]]:
    issues: Dict[str, List[str]] = {
        "quantity_mismatches": [],
        "missing_basis": [],
    }

    cash_symbols = [h.symbol for h in holdings if getattr(h, "is_cash_equivalent", False)]
    mismatches = compare_holdings_to_lots(
        holdings,
        lots,
        exclude_symbols=cash_symbols,
    )
    for symbol, diff in mismatches:
        issues["quantity_mismatches"].append(
            f"{symbol}: holdings vs lots differ by {diff:.4f} shares"
        )

    for lot_id in find_lots_missing_basis(lots):
        issues["missing_basis"].append(f"Lot {lot_id} has no cost basis")

    return issues
