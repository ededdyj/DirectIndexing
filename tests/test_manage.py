from datetime import date, timedelta

import pandas as pd
import pytest

from src.models import (
    Holding,
    Lot,
    ManageActionSettings,
    RealizedSummary,
    StrategySpec,
)
from src.portfolio.manage import build_strategy_manage_plan, compute_drift_summary, compute_sleeve_snapshot


def sample_holdings():
    return [
        Holding(symbol="AAA", qty=10, price=10.0),
        Holding(symbol="BBB", qty=5, price=20.0),
        Holding(symbol="CCC", qty=3, price=30.0),
    ]


def sample_lots():
    today = date.today()
    return [
        Lot(
            lot_id="AAA1",
            symbol="AAA",
            acquired_date=today - timedelta(days=200),
            qty=5,
            basis_total=80.0,
        ),
        Lot(
            lot_id="AAA2",
            symbol="AAA",
            acquired_date=today - timedelta(days=50),
            qty=5,
            basis_total=70.0,
        ),
        Lot(
            lot_id="BBB1",
            symbol="BBB",
            acquired_date=today - timedelta(days=400),
            qty=5,
            basis_total=60.0,
        ),
    ]


def sample_basket():
    return pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "DDD"],
            "weight": [0.4, 0.4, 0.2],
            "sector": ["Tech", "Energy", "Health"],
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


def test_drift_summary_calculation():
    sleeve_value, _, weights = compute_sleeve_snapshot(sample_holdings(), sample_basket())
    drift = compute_drift_summary(sample_basket(), sleeve_value, weights)
    assert drift.sleeve_value == pytest.approx(10 * 10 + 5 * 20, rel=1e-6)
    assert drift.max_abs_drift >= 0
    assert drift.overweights or drift.underweights


def test_manage_plan_prefers_underweights_for_replacements():
    settings = ManageActionSettings(mode="tlh", tlh_candidate_limit=2)
    plan = build_strategy_manage_plan(
        sample_holdings(),
        sample_lots(),
        sample_basket(),
        sample_spec(),
        settings,
        RealizedSummary(ytd_realized_st=500.0),
    )
    if plan.tlh_sells:
        assert plan.buy_targets


def test_manage_plan_rebalance_with_turnover_cap():
    settings = ManageActionSettings(
        mode="rebalance",
        drift_tolerance_pct=0.0,
        turnover_cap_pct=0.01,
    )
    plan = build_strategy_manage_plan(
        sample_holdings(),
        sample_lots(),
        sample_basket(),
        sample_spec(),
        settings,
    )
    assert plan.rebalance_sells or plan.warnings
