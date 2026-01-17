from __future__ import annotations

from typing import Iterable, List, Optional

from src.models import RealizedGainLossRow, RealizedSummary, Term

GOAL_OFFSET_GAINS = "offset_gains"
GOAL_OPPORTUNISTIC = "opportunistic"
LOSS_TARGET_TOLERANCE = 0.95


def summarize_realized(
    rows: Iterable[RealizedGainLossRow], warnings: Optional[List[str]] = None
) -> RealizedSummary:
    row_list = list(rows)
    st_total = sum(r.realized_gain_loss for r in row_list if r.term == Term.SHORT)
    lt_total = sum(r.realized_gain_loss for r in row_list if r.term == Term.LONG)
    unknown_total = sum(
        r.realized_gain_loss for r in row_list if r.term not in {Term.SHORT, Term.LONG}
    )
    wash_total = sum((r.wash_sale_disallowed or 0.0) for r in row_list)
    summary = RealizedSummary(
        ytd_realized_st=st_total,
        ytd_realized_lt=lt_total,
        ytd_realized_unknown=unknown_total,
        ytd_realized_total=st_total + lt_total + unknown_total,
        ytd_wash_sale_disallowed_total=wash_total,
        rows_count=len(row_list),
        warnings=list(warnings or []),
    )
    if not row_list:
        summary.warnings.append("No realized transactions detected; assuming $0 realized gains.")
    return summary


def determine_priority_term(summary: Optional[RealizedSummary]) -> Optional[Term]:
    if not summary:
        return None
    if summary.ytd_realized_st > 0:
        return Term.SHORT
    if summary.ytd_realized_lt > 0:
        return Term.LONG
    return None


def compute_loss_target(summary: Optional[RealizedSummary], goal: str) -> float:
    if not summary or goal != GOAL_OFFSET_GAINS:
        return 0.0
    net_st = max(0.0, summary.ytd_realized_st)
    net_lt = max(0.0, summary.ytd_realized_lt)
    net_unknown = max(0.0, summary.ytd_realized_unknown)
    return net_st + net_lt + net_unknown


def format_goal_options() -> List[str]:
    return [GOAL_OFFSET_GAINS, GOAL_OPPORTUNISTIC]
