from src.models import ReplacementBasket, TLHCandidate, Term
from src.portfolio.proposals import build_proposal, export_order_checklist


def test_build_proposal_and_export():
    candidate = TLHCandidate(
        symbol="ABC",
        lot_id="LOT1",
        qty=50,
        basis_total=2000,
        current_value=1500,
        unrealized_pl=-500,
        pl_pct=-0.25,
        term=Term.SHORT,
        notes=["Sample note"],
    )
    replacements = {"ABC": [ReplacementBasket(symbol="SPY", weight=1.0)]}
    proposal = build_proposal([candidate], replacements)
    assert proposal.expected_realized_loss == 500
    assert proposal.sells[0].symbol == "ABC"
    assert proposal.buys[0].symbol == "SPY"

    csv_text = export_order_checklist(proposal)
    assert "symbol,side,qty,rationale" in csv_text.splitlines()[0]
    assert "ABC" in csv_text
