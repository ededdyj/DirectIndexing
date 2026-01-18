from __future__ import annotations

from datetime import datetime
from typing import Dict, List

from src.models import (
    PlanNarrative,
    Proposal,
    StrategyManagePlan,
    TransitionPlan,
    WithdrawalProposal,
)


def render_plan_narrative(plan_type: str, context: Dict) -> PlanNarrative:
    plan_type = plan_type.lower()
    if plan_type == "tlh":
        return _tlh_narrative(context)
    if plan_type == "withdrawal":
        return _withdrawal_narrative(context)
    if plan_type == "transition":
        return _transition_narrative(context)
    if plan_type == "manage":
        return _manage_narrative(context)
    raise ValueError(f"Unknown plan type: {plan_type}")


def _tlh_narrative(context: Dict) -> PlanNarrative:
    proposal: Proposal = context.get("proposal")
    loss_threshold = context.get("loss_threshold", 0)
    loss_pct_threshold = context.get("loss_pct_threshold", 0)
    tlh_goal = context.get("tlh_goal", "unknown")
    loss_budget = context.get("loss_budget", 0)
    missing_gains = context.get("missing_gains_report", False)
    health_overrides = context.get("health_overrides", False)
    replacement_style = context.get("replacement_style", "Sector-aware baskets")

    metrics = {
        "Expected realized loss": _currency(-proposal.expected_realized_loss),
        "Loss threshold": _currency(loss_threshold),
        "Loss % threshold": f"{loss_pct_threshold:.2f}%",
        "Loss budget": _currency(loss_budget),
    }

    bullets = [
        "Objective: harvest losses while keeping exposure consistent with the current strategy sleeve.",
        f"Candidates met both ${loss_threshold:,.0f} and {loss_pct_threshold:.0f}% loss thresholds to ensure material tax impact.",
        f"Goal = {tlh_goal.replace('_', ' ')}; loss budget remaining after this plan is {metrics['Loss budget']}.",
        "Ordering followed MinTax buckets: ST losses → LT losses → LT gains → ST gains as a last resort.",
        f"Replacement approach: {replacement_style}; sector-aware swaps minimize drift and avoid generic ETFs when possible.",
        "Wash-sale guard considers only visible account trades; upload recent trades for stronger protection.",
    ]

    warnings = _base_warnings(missing_gains, health_overrides)
    if proposal.warnings:
        warnings.extend(proposal.warnings)

    next_steps = [
        "Review the recommended sells/buys and confirm they align with cash needs and constraints.",
        "Enter specific-lot orders at your broker (no automation is performed).",
        "Re-upload fresh PortfolioDownload and Gains & Losses files after trades settle to refresh the plan.",
    ]

    return PlanNarrative(
        title="Tax-Loss Harvesting Plan Narrative",
        bullets=bullets,
        metrics=metrics,
        warnings=warnings,
        next_steps=next_steps,
    )


def _withdrawal_narrative(context: Dict) -> PlanNarrative:
    proposal: WithdrawalProposal = context.get("proposal")
    goal = context.get("goal", "min_tax")
    missing_gains = context.get("missing_gains_report", False)
    health_overrides = context.get("health_overrides", False)

    metrics = {
        "Cash available": _currency(proposal.cash_available),
        "Cash needed from sells": _currency(proposal.amount_needed_from_sales),
        "Total proceeds": _currency(proposal.total_expected_proceeds),
        "Estimated tax": _currency(proposal.estimated_tax_cost),
    }

    bullets = [
        "Objective: raise requested cash while minimizing tax drag and maintaining diversification.",
        "Cash equivalents (sweep funds) were tapped first; sells cover only the shortfall plus any buffer.",
        f"Sell ordering followed MinTax buckets with liquidation goal = {goal} to manage drift vs. tax cost.",
        "Lots with missing acquisition dates were excluded by default to avoid audit risk (unless manually included).",
        "Drift metrics highlight how the sell set affects the sleeve; review before executing trades.",
    ]

    warnings = _base_warnings(missing_gains, health_overrides)
    if proposal.warnings:
        warnings.extend(proposal.warnings)

    next_steps = [
        "Execute the sell checklist in your brokerage account using specific-lot instructions.",
        "Confirm proceeds cover the withdrawal + buffer, then transfer cash externally if needed.",
        "Upload updated holdings/lots files after settlement to refresh drift and cash balances.",
    ]

    return PlanNarrative(
        title="Withdrawal Plan Narrative",
        bullets=bullets,
        metrics=metrics,
        warnings=warnings,
        next_steps=next_steps,
    )


def _transition_narrative(context: Dict) -> PlanNarrative:
    plan: TransitionPlan = context.get("plan")
    index_name = context.get("index_name", "strategy")
    screens = context.get("screens", [])
    missing_gains = context.get("missing_gains_report", False)

    metrics = {
        "Allocation amount": _currency(plan.allocation_amount),
        "Cash used": _currency(plan.cash_used),
        "Cash from sells": _currency(plan.cash_needed_from_sales),
        "Estimated tax": _currency(plan.estimated_tax.total_tax),
    }

    screen_text = ", ".join(screens) if screens else "none"
    bullets = [
        f"Objective: fund {plan.allocation_amount:,.0f} allocation into the {index_name.upper()} basket.",
        f"Cash equivalents covered {metrics['Cash used']} before triggering tax-aware sells for the remainder.",
        "Sell ordering reused the withdrawal MinTax hierarchy, minimizing ST gains and reusing losses to offset existing gains.",
        "Buy targets were derived directly from the target basket weights; estimated shares shown when prices were available.",
        f"Screens/exclusions in effect: {screen_text}. Removed symbols were renormalized out of the basket.",
        "Diversification caveat: weights may drift if prices move materially before execution; rerun after trades settle.",
    ]

    warnings = _base_warnings(missing_gains, False)
    warnings.extend(plan.warnings or [])

    next_steps = [
        "Execute the sell orders first, respecting specific-lot IDs.",
        "Once cash is available, enter the buy tickets using target dollars/shares from the plan.",
        "Upload fresh holdings/lots plus the updated basket to confirm allocation progress.",
    ]

    return PlanNarrative(
        title="Strategy Transition Narrative",
        bullets=bullets,
        metrics=metrics,
        warnings=warnings,
        next_steps=next_steps,
    )


def _manage_narrative(context: Dict) -> PlanNarrative:
    plan: StrategyManagePlan = context.get("plan")
    settings = context.get("settings")

    metrics = {
        "Sleeve value": _currency(plan.drift_summary.sleeve_value),
        "Max drift": f"{plan.drift_summary.max_abs_drift:.2%}",
        "Total drift": f"{plan.drift_summary.total_abs_drift:.2%}",
        "TLH trades": str(len(plan.tlh_sells)),
        "Rebalance sells": str(len(plan.rebalance_sells)),
    }

    bullets = [
        "Objective: keep the direct indexing sleeve aligned with target weights while realizing tax alpha when possible.",
        f"Drift tolerance = {settings.drift_tolerance_pct:.2%} with turnover cap {settings.turnover_cap_pct:.2%}; overweights beyond that were addressed.",
        "TLH module reused the MinTax ordering, and replacements pull from current underweights so the basket stays diversified.",
        "Rebalance sells prefer loss lots or lower-gain LT lots; ST gains surfaced only if necessary to meet drift goals.",
        "Buy targets direct new dollars into underweights using sleeve weights; ETF fallbacks flagged in warnings when needed.",
    ]

    warnings = plan.warnings.copy()
    warnings.extend(_base_warnings(False, False))

    next_steps = [
        "Review TLH vs. rebalance sells separately; cancel any trade that conflicts with compliance or client constraints.",
        "Execute buys only after matching sells settle to avoid wash-sale issues.",
        "Re-upload holdings/lots + target basket after trades settle to confirm drift and tax outcomes.",
    ]

    return PlanNarrative(
        title="Strategy Management Narrative",
        bullets=bullets,
        metrics=metrics,
        warnings=warnings,
        next_steps=next_steps,
    )


def _base_warnings(missing_gains: bool, health_overrides: bool) -> List[str]:
    warnings = [
        "Account-only wash-sale guard; external accounts may create disallowed losses.",
        "Narrative is informational, not tax advice.",
    ]
    if missing_gains:
        warnings.append("Realized gains report missing; tax context assumes $0 realized gains YTD.")
    if health_overrides:
        warnings.append("Data health overrides were accepted; review inputs before trading.")
    return warnings


def _currency(value: float) -> str:
    return f"${value:,.2f}"
