import pandas as pd
import pytest

from src.models import StrategySpec
from src.portfolio.strategy import build_target_basket


def base_universe():
    return pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "VMFXX", "CCC"],
            "weight": [0.4, 0.3, 0.2, 0.1],
            "sector": ["Tech", "Energy", "Cash", "Health"],
        }
    )


def make_spec(**kwargs):
    params = dict(
        index_name="sp500",
        holdings_count=3,
        max_single_name_weight=0.5,
        screens={},
        excluded_symbols=[],
        include_cash_equivalents=False,
    )
    params.update(kwargs)
    return StrategySpec(**params)


def test_weights_renormalize_after_filtering():
    spec = make_spec()
    basket, warnings = build_target_basket(base_universe(), spec)
    assert pytest.approx(basket["weight"].sum(), rel=1e-6) == 1.0
    assert "VMFXX" not in basket["symbol"].values


def test_max_weight_cap_and_limit():
    spec = make_spec(max_single_name_weight=0.35, holdings_count=3)
    basket, _ = build_target_basket(base_universe(), spec)
    assert len(basket) == 3
    assert basket["weight"].max() <= 0.35 + 1e-9


def test_excluded_symbols_removed():
    spec = make_spec(excluded_symbols=["BBB"])
    basket, _ = build_target_basket(base_universe(), spec)
    assert "BBB" not in basket["symbol"].values


def test_cash_equivalent_retained_when_allowed():
    spec = make_spec(include_cash_equivalents=True)
    basket, _ = build_target_basket(base_universe(), spec)
    assert "VMFXX" in basket["symbol"].values
