from io import StringIO

from src.parsing.common import normalize_header
from src.parsing.lots_parser import parse_lots_csv


def test_header_normalization():
    assert normalize_header("Market Value ($)") == "market_value"
    assert normalize_header("  Cost Basis Total  ") == "cost_basis_total"


def test_lots_parsing_with_basis_per_share():
    csv_data = StringIO(
        "Ticker,Purchase Date,Shares,Basis_Per_Share,Lot\n"
        "AAPL,2023-01-05,10,150,L123\n"
    )
    lots = parse_lots_csv(csv_data)
    assert len(lots) == 1
    lot = lots[0]
    assert lot.symbol == "AAPL"
    assert lot.basis_total == 1500
    assert lot.lot_id == "L123"
