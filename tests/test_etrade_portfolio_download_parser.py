from pathlib import Path

from src.parsing.etrade_portfolio_download_parser import (
    build_etrade_template_csv,
    parse_etrade_portfolio_download,
)


FIXTURE_PATH = Path("tests/fixtures/etrade_portfolio_download_sample.csv")


def test_parse_portfolio_download_extracts_holdings_and_lots():
    result = parse_etrade_portfolio_download(FIXTURE_PATH)

    assert result.detected_format.startswith("E*TRADE")
    assert result.positions_header == [
        "Symbol",
        "Qty #",
        "Value $",
        "Total Cost",
    ]
    assert result.account_summary
    assert result.account_summary.account == "Sample Brokerage -0001"

    assert len(result.holdings) == 2
    aaa = result.holdings[0]
    assert aaa.symbol == "AAA"
    assert aaa.qty == 100.0
    assert aaa.market_value == 1500.0
    assert round(aaa.price, 2) == 15.0

    assert len(result.lots) == 2
    lot_dates = sorted(lot.acquired_date.isoformat() for lot in result.lots)
    assert lot_dates == ["2022-01-05", "2023-03-15"]
    assert all(lot.symbol == "AAA" for lot in result.lots)
    assert all(lot.current_value is not None for lot in result.lots)

    assert any("missing acquired date" in warn.lower() for warn in result.warnings)


def test_template_export_contains_expected_sections():
    template = build_etrade_template_csv()
    assert "Account Summary" in template
    assert "View Summary - PositionsSimple" in template
    assert "Symbol,Qty #,Value $,Total Cost" in template
