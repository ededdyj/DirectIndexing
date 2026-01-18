from datetime import date, timedelta

import pandas as pd
import pytest

from src.models import (
    Holding,
    Lot,
    RealizedSummary,
    StrategyAllocationRequest,
    StrategySpec,
    TaxRateInput,
)
from src.portfolio.transition import build_transition_plan


def make_lot(symbol: str, days_ago: int, qty: float, basis: float, lot_id: str):
    return Lot(
        lot_id=lot_id,
        symbol=symbol,
        acquired_date=date.today() - timedelta(days=days_ago),
        qty=qty,
        basis_total=basis,
    )


def sample_holdings():
    return [
        Holding(symbol="AAA", qty=10, price=50.0),
        Holding(symbol="BBB", qty=8, price=40.0),
        Holding(symbol="VMFXX", qty=1000, price=1.0, is_cash_equivalent=True),
    ]


def sample_lots():
    return [
        make_lot("AAA", 30, 5, 400.0, "AAA_ST_LOSS"),
        make_lot("AAA", 500, 5, 150.0, "AAA_LT_GAIN"),
        make_lot("BBB", 600, 8, 200.0, "BBB_LT_GAIN"),
    ]


def sample_basket():
    return pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC"],
            "weight": [0.4, 0.4, 0.2],
        }
    )


def sample_spec():
    return StrategySpec(
        index_name="sp500",
        holdings_count=3,
        max_single_name_weight=0.5,
        screens={},
        excluded_symbols=[],
    )


def test_transition_plan_uses_cash_before_sells():
    holdings = sample_holdings()
    lots = sample_lots()
    summary = RealizedSummary(ytd_realized_st=500.0)
    request = StrategyAllocationRequest(
        allocation_amount=1200.0,
        cash_buffer_pct=0.0,
        manual_cash_available=0.0,
        excluded_from_selling=[],
        tax_rates=TaxRateInput(short_term=0.3, long_term=0.15, state=0.05),
    )

    plan = build_transition_plan(
        holdings,
        lots,
        sample_basket(),
        sample_spec(),
        request,
        summary,
    )

    assert plan.cash_available >= 1000.0
    assert plan.cash_needed_from_sales > 0
    assert plan.sells
    assert plan.sells[0].lot_id == "AAA_ST_LOSS"
    assert sum(b.target_dollars for b in plan.buys) == pytest.approx(
        request.allocation_amount, rel=1e-6
    )


def test_transition_respects_exclusions():
    holdings = sample_holdings()
    lots = sample_lots()
    request = StrategyAllocationRequest(
        allocation_amount=2000.0,
        cash_buffer_pct=0.0,
        excluded_from_selling=["AAA", "BBB"],
    )
    plan = build_transition_plan(
        holdings,
        lots,
        sample_basket(),
        sample_spec(),
        request,
    )
    assert not plan.sells
    assert any("Unable" in warn for warn in plan.warnings)


def test_transition_no_sells_when_cash_sufficient():
    holdings = sample_holdings()
    lots = sample_lots()
    request = StrategyAllocationRequest(
        allocation_amount=500.0,
        cash_buffer_pct=0.0,
    )
    plan = build_transition_plan(
        holdings,
        lots,
        sample_basket(),
        sample_spec(),
        request,
    )
    assert plan.cash_needed_from_sales == 0
    assert not plan.sells
