from datetime import date, timedelta

from src.models import Holding, Lot
from src.portfolio.tlh import identify_candidates


def make_lot(symbol: str, acquired_days_ago: int, qty: float, basis: float, lot_id: str):
    acquired = date.today() - timedelta(days=acquired_days_ago)
    return Lot(
        lot_id=lot_id,
        symbol=symbol,
        acquired_date=acquired,
        qty=qty,
        basis_total=basis,
    )


def test_identify_candidates_filters_by_loss_threshold():
    holdings = [Holding(symbol="ABC", qty=100, price=5.0)]
    lots = [make_lot("ABC", acquired_days_ago=200, qty=100, basis=1000, lot_id="L1")]
    candidates = identify_candidates(
        holdings,
        lots,
        loss_threshold=200,
        loss_pct_threshold=0.05,
        max_candidates=5,
        trades=[],
    )
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.symbol == "ABC"
    assert candidate.unrealized_pl == (5 * 100) - 1000


def test_candidates_warn_when_near_long_term():
    holdings = [Holding(symbol="XYZ", qty=10, price=30.0)]
    lots = [make_lot("XYZ", acquired_days_ago=360, qty=10, basis=500, lot_id="L2")]
    candidates = identify_candidates(
        holdings,
        lots,
        loss_threshold=100,
        loss_pct_threshold=0.05,
        max_candidates=5,
        trades=[],
    )
    assert candidates
    assert any("long-term" in note for note in candidates[0].notes)
