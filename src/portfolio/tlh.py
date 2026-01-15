from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, List, Optional

from src.models import Holding, Lot, TLHCandidate, Term, Trade
from src.portfolio.analytics import price_lookup

DEFAULT_LOSS_THRESHOLD = 500.0
DEFAULT_LOSS_PCT = 0.05
NEAR_LT_DAYS = 14
WASH_WINDOW_DAYS = 31


def identify_candidates(
    holdings: List[Holding],
    lots: List[Lot],
    loss_threshold: float = DEFAULT_LOSS_THRESHOLD,
    loss_pct_threshold: float = DEFAULT_LOSS_PCT,
    max_candidates: int = 10,
    trades: Optional[Iterable[Trade]] = None,
    today: Optional[date] = None,
) -> List[TLHCandidate]:
    today = today or date.today()
    price_map = price_lookup(holdings)
    trade_list = list(trades or [])

    candidates: List[TLHCandidate] = []
    for lot in lots:
        price = price_map.get(lot.symbol)
        if not price:
            continue
        current_value = price * lot.qty
        unrealized_pl = current_value - lot.basis_total
        if lot.basis_total <= 0:
            continue
        pl_pct = unrealized_pl / lot.basis_total
        if unrealized_pl >= -abs(loss_threshold):
            continue
        if pl_pct >= -abs(loss_pct_threshold):
            continue
        notes: List[str] = []
        days_held = (today - lot.acquired_date).days
        if lot.term == Term.SHORT and days_held >= (365 - NEAR_LT_DAYS):
            notes.append(
                "Lot is within 14 days of long-term status; consider holding"
            )
        if _has_recent_buy(trade_list, lot.symbol, today):
            notes.append("Recent buy detected; wash-sale risk")
        candidates.append(
            TLHCandidate(
                symbol=lot.symbol,
                lot_id=lot.lot_id,
                qty=lot.qty,
                basis_total=lot.basis_total,
                current_value=current_value,
                unrealized_pl=unrealized_pl,
                pl_pct=pl_pct,
                term=lot.term,
                notes=notes,
            )
        )

    candidates.sort(
        key=lambda c: (
            0 if c.term == Term.SHORT else 1,
            c.unrealized_pl,
        )
    )
    return candidates[:max_candidates]


def _has_recent_buy(trades: Iterable[Trade], symbol: str, today: date) -> bool:
    for trade in trades:
        if trade.symbol.upper() != symbol.upper():
            continue
        if trade.side.upper().startswith("B"):
            if abs((today - trade.trade_date).days) <= WASH_WINDOW_DAYS:
                return True
    return False
