from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pandas as pd

from src.models import (
    BuyTargetRow,
    EstimatedTaxImpact,
    Holding,
    Lot,
    RealizedSummary,
    StrategyAllocationRequest,
    StrategySpec,
    TransitionPlan,
    Term,
)
from src.portfolio.analytics import price_lookup
from src.portfolio.liquidation import (
    TaxRates,
    build_sell_candidates,
    compute_drift_notes,
    compute_symbol_weights,
    estimate_available_cash,
    format_sells_csv,
    select_sells,
)


def _resolve_tax_rates(request: StrategyAllocationRequest) -> TaxRates:
    if request.tax_rates:
        return TaxRates(
            short_term=request.tax_rates.short_term,
            long_term=request.tax_rates.long_term,
            state=request.tax_rates.state,
        )
    return TaxRates()


def build_transition_plan(
    holdings: List[Holding],
    lots: List[Lot],
    target_basket: pd.DataFrame,
    strategy_spec: StrategySpec,
    request: StrategyAllocationRequest,
    realized_summary: Optional[RealizedSummary] = None,
) -> TransitionPlan:
    summary = realized_summary or RealizedSummary()
    tax_rates = _resolve_tax_rates(request)

    buffer_amount = request.cash_buffer_amount
    if buffer_amount is None and request.cash_buffer_pct is not None:
        buffer_amount = request.allocation_amount * request.cash_buffer_pct
    buffer_amount = buffer_amount or 0.0

    cash_available = estimate_available_cash(
        holdings,
        manual_cash=request.manual_cash_available,
        include_cash_equivalents=request.use_cash_equivalents_first,
    )
    total_need = request.allocation_amount + buffer_amount
    cash_used = min(cash_available, total_need)
    cash_needed_from_sales = max(0.0, total_need - cash_available)

    exclude_symbols = set(request.excluded_from_selling or [])
    if request.use_cash_equivalents_first:
        exclude_symbols.update(
            h.symbol
            for h in holdings
            if getattr(h, "is_cash_equivalent", False)
        )

    candidates, warnings = build_sell_candidates(
        lots,
        holdings,
        exclude_symbols=sorted(exclude_symbols),
        exclude_missing_dates=request.exclude_missing_dates,
    )

    sells, sell_warnings = select_sells(
        candidates,
        cash_needed_from_sales,
        summary,
        tax_rates,
        request.liquidation_goal,
        compute_symbol_weights(holdings),
    )
    warnings.extend(sell_warnings)

    total_proceeds = sum(s.proceeds for s in sells)
    if cash_needed_from_sales > 0 and total_proceeds < cash_needed_from_sales:
        warnings.append("Unable to fully fund strategy allocation with available lots.")

    estimated_tax = EstimatedTaxImpact(
        st_realized=sum(s.gain_loss for s in sells if s.term == Term.SHORT),
        lt_realized=sum(s.gain_loss for s in sells if s.term == Term.LONG),
        st_tax=sum(s.estimated_tax for s in sells if s.term == Term.SHORT),
        lt_tax=sum(s.estimated_tax for s in sells if s.term == Term.LONG),
    )
    estimated_tax.total_tax = estimated_tax.st_tax + estimated_tax.lt_tax

    price_map = price_lookup(holdings)
    buys, buy_warnings = _build_buy_targets(
        target_basket,
        request.allocation_amount,
        price_map,
    )
    warnings.extend(buy_warnings)

    rationale = _build_rationale(
        strategy_spec,
        summary,
        request,
        sells,
        cash_used,
        total_proceeds,
    )
    drift_notes = compute_drift_notes(holdings, sells, cash_needed_from_sales)

    plan = TransitionPlan(
        allocation_amount=request.allocation_amount,
        buffer_amount=buffer_amount,
        cash_available=cash_available,
        cash_used=cash_used,
        cash_needed_from_sales=cash_needed_from_sales,
        sells=sells,
        estimated_tax=estimated_tax,
        buys=buys,
        warnings=warnings,
        drift_metrics=drift_notes,
        rationale_summary=rationale,
    )
    return plan


def _build_buy_targets(
    basket_df: pd.DataFrame,
    allocation_amount: float,
    price_map: Dict[str, float],
) -> Tuple[List[BuyTargetRow], List[str]]:
    warnings: List[str] = []
    buys: List[BuyTargetRow] = []
    if basket_df is None or basket_df.empty:
        warnings.append("Target basket is empty; no buys generated.")
        return buys, warnings

    weights = basket_df["weight"]
    total_weight = weights.sum()
    if total_weight <= 0:
        warnings.append("Target basket weights sum to zero.")
        return buys, warnings
    normalized_weights = weights / total_weight

    for idx, row in basket_df.iterrows():
        symbol = row["symbol"].upper()
        weight = float(normalized_weights.iloc[idx])
        target_dollars = allocation_amount * weight
        price = price_map.get(symbol)
        est_shares = None
        if price and price > 0:
            est_shares = target_dollars / price
        else:
            warnings.append(f"Missing price for {symbol}; share estimate skipped.")
        buys.append(
            BuyTargetRow(
                symbol=symbol,
                target_weight=weight,
                target_dollars=target_dollars,
                price=price,
                est_shares=est_shares,
            )
        )
    return buys, warnings


def _build_rationale(
    strategy_spec: StrategySpec,
    summary: RealizedSummary,
    request: StrategyAllocationRequest,
    sells: List,
    cash_used: float,
    proceeds: float,
) -> str:
    notes = []
    if request.tax_rates:
        notes.append(
            "Applied custom tax rates for estimating sale impact."
        )
    else:
        notes.append("Used default tax rate assumptions for MinTax ordering.")
    if summary and (summary.ytd_realized_st or summary.ytd_realized_lt):
        notes.append(
            "Realized gains context provided; losses prioritized to offset ST gains first."
        )
    else:
        notes.append("No realized gains file uploaded; assuming $0 realized gains.")
    notes.append(
        f"Used ${cash_used:,.0f} cash equivalents before selling {len(sells)} lots to raise ${proceeds:,.0f}."
    )
    notes.append(
        f"Liquidation goal: {request.liquidation_goal} for {strategy_spec.index_name} basket."
    )
    return " ".join(notes)


def format_buy_targets_csv(buys: List[BuyTargetRow]) -> str:
    from io import StringIO
    import csv

    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Symbol", "Target weight", "Target $", "Price", "Est shares"])
    for buy in buys:
        writer.writerow(
            [
                buy.symbol,
                round(buy.target_weight, 6),
                round(buy.target_dollars, 2),
                "" if buy.price is None else round(buy.price, 4),
                "" if buy.est_shares is None else round(buy.est_shares, 4),
            ]
        )
    return buffer.getvalue()


def format_transition_summary(plan: TransitionPlan) -> str:
    lines = [
        f"Allocation amount: ${plan.allocation_amount:,.2f}",
        f"Buffer amount: ${plan.buffer_amount:,.2f}",
        f"Cash available: ${plan.cash_available:,.2f}",
        f"Cash needed from sales: ${plan.cash_needed_from_sales:,.2f}",
        f"Estimated tax (ST/LT/Total): ${plan.estimated_tax.st_tax:,.2f} / ${plan.estimated_tax.lt_tax:,.2f} / ${plan.estimated_tax.total_tax:,.2f}",
        "Rationale:",
        plan.rationale_summary,
    ]
    if plan.drift_metrics:
        lines.append("Drift metrics:")
        lines.extend(plan.drift_metrics)
    if plan.warnings:
        lines.append("Warnings:")
        lines.extend(plan.warnings)
    return "\n".join(lines)
