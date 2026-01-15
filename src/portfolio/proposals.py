from __future__ import annotations

import csv
from io import StringIO
from typing import Dict, Iterable, List, Tuple

from src.models import OrderChecklistRow, Proposal, ReplacementBasket, TLHCandidate


def build_proposal(
    selected_candidates: Iterable[TLHCandidate],
    replacement_plan: Dict[str, List[ReplacementBasket]],
) -> Proposal:
    candidates = list(selected_candidates)
    sells: List[OrderChecklistRow] = []
    buys: List[OrderChecklistRow] = []
    notes: List[str] = []
    warnings: List[str] = []

    for candidate in candidates:
        sells.append(
            OrderChecklistRow(
                symbol=candidate.symbol,
                side="SELL",
                qty=candidate.qty,
                rationale=f"Harvest loss from lot {candidate.lot_id}",
            )
        )
        if candidate.notes:
            notes.extend(candidate.notes)

        replacements = replacement_plan.get(candidate.symbol)
        if not replacements:
            warnings.append(f"No replacement basket for {candidate.symbol}")
            continue
        target_value = abs(candidate.current_value)
        for basket in replacements:
            buy_value = round(target_value * basket.weight, 2)
            buys.append(
                OrderChecklistRow(
                    symbol=basket.symbol,
                    side="BUY",
                    qty=buy_value,
                    rationale=(
                        f"Proxy for {candidate.symbol}; allocate ${buy_value:,.2f}"
                    ),
                )
            )

    expected_loss = sum(-min(c.unrealized_pl, 0) for c in candidates)

    return Proposal(
        sells=sells,
        buys=buys,
        expected_realized_loss=expected_loss,
        notes=notes,
        warnings=warnings,
    )


def proposal_to_rows(proposal: Proposal) -> List[Tuple[str, str, float, str]]:
    rows = []
    for row in proposal.sells + proposal.buys:
        rows.append((row.symbol, row.side, row.qty, row.rationale or ""))
    return rows


def export_order_checklist(proposal: Proposal) -> str:
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["symbol", "side", "qty", "rationale"])
    for row in proposal_to_rows(proposal):
        writer.writerow(row)
    return buffer.getvalue()
