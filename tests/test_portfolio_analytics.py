from datetime import date

from src.models import Holding, Lot
from src.portfolio.analytics import price_lookup, run_health_checks


def test_health_checks_ignore_cash_equivalent_holdings():
    holdings = [
        Holding(symbol="AAA", qty=100, price=10.0),
        Holding(symbol="VMFXX", qty=1000, price=1.0, is_cash_equivalent=True),
    ]
    lots = [
        Lot(
            lot_id="AAA_1",
            symbol="AAA",
            acquired_date=date(2023, 1, 1),
            qty=100,
            basis_total=1200,
        )
    ]

    health = run_health_checks(holdings, lots)

    assert not health["quantity_mismatches"]


def test_price_lookup_skips_cash_equivalents():
    holdings = [
        Holding(symbol="AAA", qty=10, price=5.0),
        Holding(symbol="VMFXX", qty=100, price=1.0, is_cash_equivalent=True),
    ]

    lookup = price_lookup(holdings)

    assert "AAA" in lookup
    assert "VMFXX" not in lookup
