from pathlib import Path

from src.parsing.etrade_gains_losses_parser import parse_etrade_gains_losses_csv
from src.portfolio.tax_context import GOAL_OFFSET_GAINS, compute_loss_target, summarize_realized


FIXTURE_PATH = Path("tests/fixtures/etrade_gains_losses_sample.csv")


def test_parse_gains_losses_extracts_rows_and_summary():
    result = parse_etrade_gains_losses_csv(FIXTURE_PATH)

    assert result.header[0].startswith("Symbol")
    assert not result.warnings
    assert len(result.rows) == 3

    first = result.rows[0]
    assert first.symbol == "AAA"
    assert first.term.value == "LT"
    assert first.realized_gain_loss == -200.0

    summary = summarize_realized(result.rows, warnings=result.warnings)
    assert summary.ytd_realized_st == -300.0
    assert summary.ytd_realized_lt == -50.0
    assert summary.ytd_wash_sale_disallowed_total == 25.0
    assert summary.rows_count == 3

    target = compute_loss_target(summary, GOAL_OFFSET_GAINS)
    assert target == 0.0  # net gains are negative so no loss target
