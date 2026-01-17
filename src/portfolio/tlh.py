from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, List, Optional

from src.models import (
    Holding,
    Lot,
    RealizedSummary,
    TLHCandidate,
    Term,
    Trade,
)
from src.portfolio.analytics import price_lookup
from src.portfolio.tax_context import (
    GOAL_OFFSET_GAINS,
    LOSS_TARGET_TOLERANCE,
    determine_priority_term,
)

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
    realized_summary: Optional[RealizedSummary] = None,
    tlh_goal: str = GOAL_OFFSET_GAINS,
    loss_target: float = 0.0,
) -> List[TLHCandidate]:
    today = today or date.today()
    price_map = price_lookup(holdings)
    trade_list = list(trades or [])
    priority_term = determine_priority_term(realized_summary)

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

    def _sort_key(candidate: TLHCandidate):
        primary = 0
        if priority_term:
            primary = 0 if candidate.term == priority_term else 1
        else:
            primary = 0 if candidate.term == Term.SHORT else 1
        secondary = 0 if candidate.term == Term.SHORT else 1
        return (primary, secondary, candidate.unrealized_pl)

    candidates.sort(key=_sort_key)

    filtered: List[TLHCandidate] = []
    cumulative_loss = 0.0
    for candidate in candidates:
        filtered.append(candidate)
        if tlh_goal == GOAL_OFFSET_GAINS and loss_target > 0:
            cumulative_loss += -candidate.unrealized_pl
            if cumulative_loss >= loss_target * LOSS_TARGET_TOLERANCE:
                break
        if len(filtered) >= max_candidates:
            break
    return filtered


def _has_recent_buy(trades: Iterable[Trade], symbol: str, today: date) -> bool:
    for trade in trades:
        if trade.symbol.upper() != symbol.upper():
            continue
        if trade.side.upper().startswith("B"):
            if abs((today - trade.trade_date).days) <= WASH_WINDOW_DAYS:
                return True
    return False
