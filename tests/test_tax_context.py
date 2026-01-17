from datetime import date

from src.models import RealizedGainLossRow, Term
from src.portfolio.tax_context import (
    GOAL_OFFSET_GAINS,
    GOAL_OPPORTUNISTIC,
    compute_loss_target,
    determine_priority_term,
    summarize_realized,
)


def make_row(symbol: str, term: Term, gain: float) -> RealizedGainLossRow:
    return RealizedGainLossRow(
        symbol=symbol,
        quantity=1.0,
        date_acquired=date(2023, 1, 1),
        date_sold=date(2025, 1, 1),
        proceeds=100.0,
        cost_basis=90.0,
        realized_gain_loss=gain,
        term=term,
    )


def test_summarize_realized_and_priority_term():
    rows = [
        make_row("AAA", Term.SHORT, 200.0),
        make_row("BBB", Term.LONG, -50.0),
    ]
    summary = summarize_realized(rows)
    assert summary.ytd_realized_st == 200.0
    assert summary.ytd_realized_lt == -50.0
    assert summary.ytd_realized_total == 150.0
    assert determine_priority_term(summary) == Term.SHORT


def test_compute_loss_target_respects_goal():
    rows = [make_row("AAA", Term.LONG, 150.0)]
    summary = summarize_realized(rows)
    assert compute_loss_target(summary, GOAL_OFFSET_GAINS) == 150.0
    assert compute_loss_target(summary, GOAL_OPPORTUNISTIC) == 0.0
