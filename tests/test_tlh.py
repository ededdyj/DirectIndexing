from datetime import date, timedelta

from src.models import Holding, Lot, RealizedSummary, Term
from src.portfolio.tax_context import GOAL_OFFSET_GAINS
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


def test_candidates_prioritize_short_term_when_realized_gains_exist():
    holdings = [
        Holding(symbol="AAA", qty=10, price=5.0),
        Holding(symbol="BBB", qty=10, price=5.0),
    ]
    lots = [
        make_lot("AAA", acquired_days_ago=100, qty=10, basis=150.0, lot_id="S1"),
        make_lot("BBB", acquired_days_ago=800, qty=10, basis=150.0, lot_id="L1"),
    ]
    summary = RealizedSummary(ytd_realized_st=1000.0, ytd_realized_lt=0.0)

    candidates = identify_candidates(
        holdings,
        lots,
        loss_threshold=10,
        loss_pct_threshold=0.01,
        max_candidates=5,
        trades=[],
        realized_summary=summary,
        tlh_goal=GOAL_OFFSET_GAINS,
        loss_target=500.0,
    )

    assert candidates
    assert candidates[0].term == Term.SHORT


def test_candidates_stop_when_loss_target_met():
    holdings = [Holding(symbol="AAA", qty=3, price=5.0)]
    lots = [
        make_lot("AAA", acquired_days_ago=50, qty=1, basis=120.0, lot_id="S1"),
        make_lot("AAA", acquired_days_ago=60, qty=1, basis=120.0, lot_id="S2"),
        make_lot("AAA", acquired_days_ago=70, qty=1, basis=120.0, lot_id="S3"),
    ]
    summary = RealizedSummary(ytd_realized_st=100.0, ytd_realized_lt=0.0)

    candidates = identify_candidates(
        holdings,
        lots,
        loss_threshold=5,
        loss_pct_threshold=0.01,
        max_candidates=5,
        trades=[],
        realized_summary=summary,
        tlh_goal=GOAL_OFFSET_GAINS,
        loss_target=100.0,
    )

    assert len(candidates) <= 3
    cumulative = sum(-c.unrealized_pl for c in candidates)
    assert cumulative >= 95.0  # 100 target with tolerance
