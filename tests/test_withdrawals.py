from datetime import date, timedelta

from src.models import Holding, Lot, RealizedSummary
from src.portfolio.withdrawals import TaxRates, build_withdrawal_proposal


def build_lot(symbol: str, days_ago: int, qty: float, basis_total: float, lot_id: str):
    return Lot(
        lot_id=lot_id,
        symbol=symbol,
        acquired_date=date.today() - timedelta(days=days_ago),
        qty=qty,
        basis_total=basis_total,
    )


def test_withdrawal_prefers_losses_before_gains():
    holdings = [
        Holding(symbol="AAA", qty=100, price=10.0),
        Holding(symbol="BBB", qty=100, price=20.0),
    ]
    lots = [
        build_lot("AAA", days_ago=30, qty=10, basis_total=150.0, lot_id="AAA_ST_LOSS"),
        build_lot("AAA", days_ago=800, qty=5, basis_total=40.0, lot_id="AAA_LT_GAIN"),
        build_lot("BBB", days_ago=900, qty=5, basis_total=50.0, lot_id="BBB_LT_GAIN"),
    ]
    summary = RealizedSummary(ytd_realized_st=500.0)

    proposal = build_withdrawal_proposal(
        holdings,
        lots,
        summary,
        withdrawal_amount=500.0,
        cushion_pct=0.0,
        manual_cash=0.0,
        tax_rates=TaxRates(short_term=0.3, long_term=0.15, state=0.05),
        goal="min_tax",
    )

    assert proposal.sells
    assert proposal.sells[0].lot_id == "AAA_ST_LOSS"
    assert proposal.estimated_realized_st <= 0  # harvested loss first


def test_withdrawal_respects_exclusions():
    holdings = [Holding(symbol="AAA", qty=50, price=10.0)]
    lots = [
        build_lot("AAA", days_ago=400, qty=10, basis_total=50.0, lot_id="AAA_GAIN"),
    ]

    proposal = build_withdrawal_proposal(
        holdings,
        lots,
        None,
        withdrawal_amount=100.0,
        cushion_pct=0.0,
        manual_cash=0.0,
        tax_rates=TaxRates(),
        goal="min_tax",
        exclude_symbols=["AAA"],
    )

    assert not proposal.sells
    assert proposal.total_expected_proceeds == 0
