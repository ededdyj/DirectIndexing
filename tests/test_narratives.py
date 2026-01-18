from datetime import datetime, date

from src.models import (
    BuyTargetRow,
    EstimatedTaxImpact,
    ManageActionSettings,
    OrderChecklistRow,
    PlanNarrative,
    Proposal,
    RealizedSummary,
    SellLotRecommendation,
    StrategyManagePlan,
    TransitionPlan,
    WithdrawalProposal,
    DriftEntry,
    DriftSummary,
)
from src.portfolio.narratives import render_plan_narrative


def test_tlh_narrative_includes_mintax_language():
    proposal = Proposal(
        sells=[OrderChecklistRow(symbol="AAA", side="SELL", qty=10)],
        buys=[],
        expected_realized_loss=-500.0,
    )
    narrative = render_plan_narrative(
        "tlh",
        {
            "proposal": proposal,
            "loss_threshold": 500,
            "loss_pct_threshold": 5,
            "tlh_goal": "offset_gains",
            "loss_budget": 1000,
            "missing_gains_report": False,
            "health_overrides": False,
            "replacement_style": "Sector-aware replacements",
        },
    )
    assert any("MinTax" in bullet for bullet in narrative.bullets)


def test_withdrawal_narrative_mentions_cash_and_min_tax():
    proposal = WithdrawalProposal(
        requested_amount=1000,
        buffer_amount=50,
        cash_available=600,
        amount_needed_from_sales=400,
        total_expected_proceeds=450,
        estimated_realized_st=-200,
        estimated_realized_lt=-100,
        estimated_tax_cost=50,
        sells=[],
    )
    narrative = render_plan_narrative(
        "withdrawal",
        {
            "proposal": proposal,
            "goal": "min_tax",
            "missing_gains_report": True,
            "health_overrides": True,
        },
    )
    assert "cash" in " ".join(narrative.bullets).lower()
    assert any("Realized gains report" in warn for warn in narrative.warnings)


def test_transition_narrative_references_targets():
    plan = TransitionPlan(
        allocation_amount=5000,
        buffer_amount=50,
        cash_available=1000,
        cash_used=900,
        cash_needed_from_sales=4150,
        sells=[],
        estimated_tax=EstimatedTaxImpact(),
        buys=[
            BuyTargetRow(
                symbol="AAA",
                target_weight=0.4,
                target_dollars=2000,
                price=10.0,
                est_shares=200,
            )
        ],
    )
    narrative = render_plan_narrative(
        "transition",
        {
            "plan": plan,
            "index_name": "sp500",
            "screens": ["oil_gas"],
            "missing_gains_report": False,
        },
    )
    assert "target basket" in " ".join(narrative.bullets).lower()


def test_manage_narrative_highlights_drift():
    drift = DriftSummary(
        sleeve_value=100000,
        max_abs_drift=0.03,
        total_abs_drift=0.05,
        overweights=[
            DriftEntry(symbol="AAA", target_weight=0.2, actual_weight=0.25, drift=0.05)
        ],
        underweights=[
            DriftEntry(symbol="BBB", target_weight=0.2, actual_weight=0.15, drift=-0.05)
        ],
    )
    plan = StrategyManagePlan(
        drift_summary=drift,
        tlh_sells=[],
        rebalance_sells=[],
        buy_targets=[],
    )
    settings = ManageActionSettings()
    narrative = render_plan_narrative("manage", {"plan": plan, "settings": settings})
    assert "drift" in " ".join(narrative.bullets).lower()
