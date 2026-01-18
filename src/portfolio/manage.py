from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

from src.models import (
    BuyTargetRow,
    DriftEntry,
    DriftSummary,
    Holding,
    Lot,
    ManageActionSettings,
    RealizedSummary,
    SellLotRecommendation,
    StrategyManagePlan,
    StrategySpec,
    Term,
)
from src.portfolio.analytics import price_lookup
from src.portfolio.liquidation import (
    TaxRates,
    build_sell_candidates,
    compute_symbol_weights,
    select_sells,
)
from src.portfolio.replacements import build_replacement_basket
from src.portfolio.tlh import identify_candidates


def compute_sleeve_snapshot(
    holdings: Sequence[Holding],
    basket_df: pd.DataFrame,
) -> Tuple[float, Dict[str, float], Dict[str, float]]:
    if basket_df is None or basket_df.empty:
        return 0.0, {}, {}
    target_symbols = set(basket_df["symbol"].str.upper())
    values: Dict[str, float] = {}
    for holding in holdings:
        if holding.symbol.upper() not in target_symbols:
            continue
        if getattr(holding, "is_cash_equivalent", False):
            continue
        value = (
            holding.market_value
            if holding.market_value is not None
            else (holding.price or 0.0) * holding.qty
        )
        values[holding.symbol.upper()] = values.get(holding.symbol.upper(), 0.0) + value
    sleeve_value = sum(values.values())
    weights = {}
    if sleeve_value > 0:
        weights = {symbol: val / sleeve_value for symbol, val in values.items()}
    return sleeve_value, values, weights


def compute_drift_summary(
    basket_df: pd.DataFrame,
    sleeve_value: float,
    actual_weights: Dict[str, float],
) -> DriftSummary:
    entries: List[DriftEntry] = []
    if basket_df is None or basket_df.empty:
        return DriftSummary(
            sleeve_value=sleeve_value,
            max_abs_drift=0.0,
            total_abs_drift=0.0,
        )
    for _, row in basket_df.iterrows():
        symbol = row["symbol"].upper()
        target_weight = float(row["weight"])
        actual = float(actual_weights.get(symbol, 0.0))
        drift = actual - target_weight
        entries.append(
            DriftEntry(
                symbol=symbol,
                target_weight=target_weight,
                actual_weight=actual,
                drift=drift,
                sector=row.get("sector"),
            )
        )
    max_abs = max((abs(e.drift) for e in entries), default=0.0)
    total_abs = sum(abs(e.drift) for e in entries)
    overweights = sorted(
        [e for e in entries if e.drift > 0],
        key=lambda e: e.drift,
        reverse=True,
    )[:10]
    underweights = sorted(
        [e for e in entries if e.drift < 0],
        key=lambda e: e.drift,
    )[:10]
    sector_drift = _compute_sector_drift(entries)
    return DriftSummary(
        sleeve_value=sleeve_value,
        max_abs_drift=max_abs,
        total_abs_drift=total_abs,
        overweights=overweights,
        underweights=underweights,
        sector_drift=sector_drift,
    )


def _compute_sector_drift(entries: Sequence[DriftEntry]) -> List[DriftEntry]:
    sector_map: Dict[str, Tuple[float, float]] = {}
    for entry in entries:
        sector = entry.sector or "Unknown"
        target_total, actual_total = sector_map.get(sector, (0.0, 0.0))
        target_total += entry.target_weight
        actual_total += entry.actual_weight
        sector_map[sector] = (target_total, actual_total)
    summary: List[DriftEntry] = []
    for sector, (target_total, actual_total) in sector_map.items():
        summary.append(
            DriftEntry(
                symbol=sector,
                target_weight=target_total,
                actual_weight=actual_total,
                drift=actual_total - target_total,
                sector=sector,
            )
        )
    summary.sort(key=lambda e: abs(e.drift), reverse=True)
    return summary[:10]


def determine_underweights(
    drift_summary: DriftSummary,
) -> Dict[str, float]:
    return {
        entry.symbol: -(entry.drift) * drift_summary.sleeve_value
        for entry in drift_summary.underweights
        if entry.drift < 0
    }


def determine_overweights(
    drift_summary: DriftSummary, tolerance: float
) -> Dict[str, float]:
    return {
        entry.symbol: entry.drift * drift_summary.sleeve_value
        for entry in drift_summary.overweights
        if entry.drift > tolerance
    }


def build_strategy_manage_plan(
    holdings: List[Holding],
    lots: List[Lot],
    basket_df: pd.DataFrame,
    spec: StrategySpec,
    settings: ManageActionSettings,
    realized_summary: Optional[RealizedSummary] = None,
) -> StrategyManagePlan:
    sleeve_value, _, actual_weights = compute_sleeve_snapshot(holdings, basket_df)
    drift_summary = compute_drift_summary(basket_df, sleeve_value, actual_weights)
    summary = realized_summary or RealizedSummary()

    warnings: List[str] = []
    notes: List[str] = []
    underweights = determine_underweights(drift_summary)
    overweights = determine_overweights(drift_summary, settings.drift_tolerance_pct)

    tlh_sells: List[SellLotRecommendation] = []
    rebalance_sells: List[SellLotRecommendation] = []
    buy_targets: Dict[str, BuyTargetRow] = {}

    if settings.mode in {"tlh", "combined"}:
        tlh_sells, tlh_buys, tlh_warnings = _build_strategy_tlh_plan(
            holdings,
            lots,
            basket_df,
            spec,
            summary,
            settings,
            underweights.copy(),
        )
        warnings.extend(tlh_warnings)
        buy_targets.update(tlh_buys)

    if settings.mode in {"rebalance", "combined"}:
        rebal_sells, rebal_buys, rebal_warnings = _build_strategy_rebalance_plan(
            holdings,
            lots,
            summary,
            settings,
            overweights,
            underweights,
            sleeve_value,
        )
        warnings.extend(rebal_warnings)
        rebalance_sells = rebal_sells
        for symbol, row in rebal_buys.items():
            if symbol in buy_targets:
                existing = buy_targets[symbol]
                existing.target_dollars += row.target_dollars
                if existing.est_shares is not None and row.est_shares is not None:
                    existing.est_shares += row.est_shares
                else:
                    existing.est_shares = None
            else:
                buy_targets[symbol] = row

    plan = StrategyManagePlan(
        drift_summary=drift_summary,
        tlh_sells=tlh_sells,
        rebalance_sells=rebalance_sells,
        buy_targets=list(buy_targets.values()),
        warnings=warnings,
        notes=notes,
    )
    return plan


def _build_strategy_tlh_plan(
    holdings: List[Holding],
    lots: List[Lot],
    basket_df: pd.DataFrame,
    spec: StrategySpec,
    summary: RealizedSummary,
    settings: ManageActionSettings,
    underweights: Dict[str, float],
) -> Tuple[List[SellLotRecommendation], Dict[str, BuyTargetRow], List[str]]:
    warnings: List[str] = []
    lot_lookup = {lot.lot_id: lot for lot in lots}
    candidates = identify_candidates(
        holdings,
        [lot for lot in lots if lot.symbol.upper() in set(basket_df["symbol"].str.upper())],
        loss_threshold=100.0,
        loss_pct_threshold=0.02,
        max_candidates=settings.tlh_candidate_limit,
        trades=[],
        realized_summary=summary,
        tlh_goal=settings.tax_goal,
        loss_target=0.0,
    )
    sells = []
    buy_rows: Dict[str, BuyTargetRow] = {}
    if not candidates:
        return sells, buy_rows, warnings

    target_weights = {
        row["symbol"].upper(): row["weight"] for _, row in basket_df.iterrows()
    }
    sleeve_value, _, actual_weights = compute_sleeve_snapshot(holdings, basket_df)
    price_map = price_lookup(holdings)

    tax_rates = TaxRates()
    for cand in candidates:
        if cand.symbol.upper() not in target_weights:
            continue
        lot = lot_lookup.get(cand.lot_id)
        price = cand.current_value / cand.qty if cand.qty else 0.0
        estimated_tax = _estimate_candidate_tax(cand.unrealized_pl, cand.term, tax_rates)
        sells.append(
            SellLotRecommendation(
                symbol=cand.symbol,
                lot_id=cand.lot_id,
                acquired_date=lot.acquired_date if lot else None,
                qty=cand.qty,
                price=price,
                proceeds=cand.current_value,
                basis=cand.basis_total,
                gain_loss=cand.unrealized_pl,
                term=cand.term,
                estimated_tax=estimated_tax,
                rationale=cand.notes or ["TLH candidate"],
            )
        )
        proceeds = cand.current_value
        allocation = _allocate_replacement_proceeds(
            cand.symbol,
            proceeds,
            underweights,
            price_map,
        )
        if not allocation:
            replacement_plan = build_replacement_basket(
                cand.symbol,
                sector=None,
                target_value=proceeds,
            )
            warnings.append(
                f"No underweight replacements available for {cand.symbol}; using ETF basket."
            )
            for row in replacement_plan:
                buy_rows[row.symbol] = BuyTargetRow(
                    symbol=row.symbol,
                    target_weight=0.0,
                    target_dollars=row.market_value,
                    price=None,
                    est_shares=None,
                )
            continue
        for symbol, dollars in allocation.items():
            price = price_map.get(symbol)
            est_shares = dollars / price if price else None
            if symbol in buy_rows:
                buy_rows[symbol].target_dollars += dollars
                if buy_rows[symbol].est_shares is not None and est_shares is not None:
                    buy_rows[symbol].est_shares += est_shares
                else:
                    buy_rows[symbol].est_shares = None
            else:
                buy_rows[symbol] = BuyTargetRow(
                    symbol=symbol,
                    target_weight=target_weights.get(symbol, 0.0),
                    target_dollars=dollars,
                    price=price,
                    est_shares=est_shares,
                )
    return sells, buy_rows, warnings


def _allocate_replacement_proceeds(
    sold_symbol: str,
    proceeds: float,
    underweights: Dict[str, float],
    price_map: Dict[str, float],
) -> Dict[str, float]:
    allocation: Dict[str, float] = {}
    for symbol in sorted(
        underweights, key=lambda s: underweights[s], reverse=True
    ):
        if symbol == sold_symbol:
            continue
        need = underweights[symbol]
        if need <= 0:
            continue
        amount = min(proceeds, need)
        if amount <= 0:
            continue
        allocation[symbol] = allocation.get(symbol, 0.0) + amount
        underweights[symbol] -= amount
        proceeds -= amount
        if proceeds <= 1e-6:
            break
    return allocation


def _build_strategy_rebalance_plan(
    holdings: List[Holding],
    lots: List[Lot],
    summary: RealizedSummary,
    settings: ManageActionSettings,
    overweights: Dict[str, float],
    underweights: Dict[str, float],
    sleeve_value: float,
) -> Tuple[List[SellLotRecommendation], Dict[str, BuyTargetRow], List[str]]:
    warnings: List[str] = []
    if not overweights:
        return [], {}, warnings

    turnover_cap = sleeve_value * settings.turnover_cap_pct
    sell_amount = sum(overweights.values())
    sell_amount = min(sell_amount, turnover_cap)
    if sell_amount <= 0:
        return [], {}, ["Turnover cap prevents rebalancing trades."]

    target_symbols = set(overweights.keys())
    filtered_lots = [lot for lot in lots if lot.symbol.upper() in target_symbols]
    tax_rates = TaxRates()
    candidates, candidate_warnings = build_sell_candidates(
        filtered_lots,
        holdings,
        exclude_symbols=[],
        exclude_missing_dates=True,
    )
    warnings.extend(candidate_warnings)
    sells, sell_warnings = select_sells(
        candidates,
        sell_amount,
        summary,
        tax_rates,
        settings.tax_goal,
        compute_symbol_weights(holdings),
    )
    warnings.extend(sell_warnings)

    proceeds = sum(s.proceeds for s in sells)
    buy_rows: Dict[str, BuyTargetRow] = {}
    if proceeds <= 0:
        return sells, buy_rows, warnings

    price_map = price_lookup(holdings)
    for symbol, dollar_gap in underweights.items():
        if dollar_gap <= 0:
            continue
        allocation = min(dollar_gap, proceeds)
        if allocation <= 0:
            continue
        proceeds -= allocation
        price = price_map.get(symbol)
        buy_rows[symbol] = BuyTargetRow(
            symbol=symbol,
            target_weight=0.0,
            target_dollars=allocation,
            price=price,
            est_shares=(allocation / price) if price else None,
        )
        if proceeds <= 0:
            break
    if proceeds > 0:
        warnings.append("Rebalance proceeds exceed underweight needs; remaining cash implied.")
    return sells, buy_rows, warnings


def _estimate_candidate_tax(gain: float, term, tax_rates: TaxRates) -> float:
    if gain >= 0:
        rate = tax_rates.long_term if term == Term.LONG else tax_rates.short_term
        return gain * (rate + tax_rates.state)
    benefit_rate = tax_rates.short_term + tax_rates.state if term == Term.SHORT else tax_rates.long_term + tax_rates.state
    return gain * benefit_rate


def format_manage_summary(plan: StrategyManagePlan) -> str:
    lines = [
        f"Sleeve value: ${plan.drift_summary.sleeve_value:,.2f}",
        f"Max abs drift: {plan.drift_summary.max_abs_drift:.2%}",
        f"Total abs drift: {plan.drift_summary.total_abs_drift:.2%}",
        f"TLH sells: {len(plan.tlh_sells)} | Rebalance sells: {len(plan.rebalance_sells)}",
    ]
    if plan.notes:
        lines.append("Notes:")
        lines.extend(plan.notes)
    if plan.warnings:
        lines.append("Warnings:")
        lines.extend(plan.warnings)
    return "\n".join(lines)
