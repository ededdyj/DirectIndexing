from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from src.models import (
    Holding,
    Lot,
    RealizedSummary,
    SellLotRecommendation,
    Term,
    WithdrawalProposal,
)
from src.portfolio.analytics import price_lookup


DEFAULT_SHORT_TERM_RATE = 0.32
DEFAULT_LONG_TERM_RATE = 0.15
DEFAULT_STATE_RATE = 0.05
LOSS_CARRY_DISCOUNT = 0.5


@dataclass
class TaxRates:
    short_term: float = DEFAULT_SHORT_TERM_RATE
    long_term: float = DEFAULT_LONG_TERM_RATE
    state: float = DEFAULT_STATE_RATE


@dataclass
class WithdrawalSettings:
    goal: str = "min_tax"
    exclude_symbols: Sequence[str] = ()
    exclude_missing_dates: bool = True
    cushion_pct: float = 0.01
    manual_cash: float = 0.0


def estimate_available_cash(holdings: Iterable[Holding], manual_cash: float = 0.0) -> float:
    cash = manual_cash
    for holding in holdings:
        if getattr(holding, "is_cash_equivalent", False):
            if holding.market_value is not None:
                cash += holding.market_value
            elif holding.price is not None:
                cash += holding.price * holding.qty
    return cash


def build_withdrawal_proposal(
    holdings: List[Holding],
    lots: List[Lot],
    realized_summary: Optional[RealizedSummary],
    withdrawal_amount: float,
    cushion_pct: float,
    manual_cash: float,
    tax_rates: TaxRates,
    goal: str,
    exclude_symbols: Sequence[str] = (),
    exclude_missing_dates: bool = True,
) -> WithdrawalProposal:
    summary = realized_summary or RealizedSummary()
    price_map = price_lookup(holdings)
    cash_available = estimate_available_cash(holdings, manual_cash=manual_cash)
    buffer_amount = max(withdrawal_amount * cushion_pct, 0.0)
    target_amount = max(0.0, withdrawal_amount + buffer_amount - cash_available)

    candidates, warnings = _build_candidates(
        lots,
        price_map,
        exclude_symbols=exclude_symbols,
        exclude_missing_dates=exclude_missing_dates,
    )

    symbol_weights = _symbol_weights(holdings)

    sells, sell_warnings = _select_sells(
        candidates,
        target_amount,
        summary,
        tax_rates,
        goal,
        symbol_weights,
    )
    warnings.extend(sell_warnings)

    total_proceeds = sum(s.proceeds for s in sells)
    est_tax_st = sum(s.estimated_tax for s in sells if s.term == Term.SHORT)
    est_tax_lt = sum(s.estimated_tax for s in sells if s.term == Term.LONG)
    realized_st = sum(s.gain_loss for s in sells if s.term == Term.SHORT)
    realized_lt = sum(s.gain_loss for s in sells if s.term == Term.LONG)

    drift_notes = _compute_drift_notes(holdings, sells, target_amount)

    if target_amount <= 0:
        warnings.append("Requested withdrawal covered by existing cash / sweep balances.")

    proposal = WithdrawalProposal(
        requested_amount=withdrawal_amount,
        buffer_amount=buffer_amount,
        cash_available=cash_available,
        amount_needed_from_sales=target_amount,
        total_expected_proceeds=total_proceeds,
        estimated_realized_st=realized_st,
        estimated_realized_lt=realized_lt,
        estimated_tax_cost=est_tax_st + est_tax_lt,
        sells=sells,
        warnings=warnings,
        drift_metrics=drift_notes,
    )

    if total_proceeds < target_amount:
        proposal.warnings.append(
            "Unable to reach requested cash target given current exclusions and data."
        )

    return proposal


def _build_candidates(
    lots: Iterable[Lot],
    price_map: Dict[str, float],
    exclude_symbols: Sequence[str],
    exclude_missing_dates: bool,
) -> Tuple[List[Dict], List[str]]:
    candidates: List[Dict] = []
    warnings: List[str] = []
    exclude_set = {sym.upper() for sym in exclude_symbols}

    for lot in lots:
        if lot.symbol.upper() in exclude_set:
            continue
        if exclude_missing_dates and lot.acquired_date is None:
            warnings.append(f"Excluded lot {lot.lot_id}: missing acquired date")
            continue
        price = price_map.get(lot.symbol)
        if not price or price <= 0:
            warnings.append(
                f"Skipping lot {lot.lot_id} for {lot.symbol}: missing current price"
            )
            continue
        proceeds = price * lot.qty
        gain = proceeds - lot.basis_total
        candidates.append(
            {
                "lot": lot,
                "price": price,
                "proceeds": proceeds,
                "gain": gain,
            }
        )
    return candidates, warnings


def _select_sells(
    candidates: List[Dict],
    target_amount: float,
    summary: RealizedSummary,
    tax_rates: TaxRates,
    goal: str,
    symbol_weights: Dict[str, float],
) -> Tuple[List[SellLotRecommendation], List[str]]:
    if target_amount <= 0:
        return [], []

    sells: List[SellLotRecommendation] = []
    warnings: List[str] = []

    loss_buckets = {
        "loss_st": [],
        "loss_lt": [],
        "gain_lt": [],
        "gain_st": [],
    }

    for cand in candidates:
        lot = cand["lot"]
        gain = cand["gain"]
        if gain < 0:
            if lot.term == Term.SHORT:
                loss_buckets["loss_st"].append(cand)
            else:
                loss_buckets["loss_lt"].append(cand)
        else:
            if lot.term == Term.LONG:
                loss_buckets["gain_lt"].append(cand)
            else:
                loss_buckets["gain_st"].append(cand)

    # Sorting heuristics
    loss_buckets["loss_st"].sort(key=lambda c: c["gain"])
    loss_buckets["loss_lt"].sort(key=lambda c: c["gain"])
    loss_buckets["gain_lt"].sort(key=_gain_sort_key)
    loss_buckets["gain_st"].sort(key=_gain_sort_key)

    bucket_order = [
        "loss_st",
        "loss_lt",
        "gain_lt",
        "gain_st",
    ]

    offsets = {
        "st": max(0.0, summary.ytd_realized_st),
        "lt": max(0.0, summary.ytd_realized_lt),
    }

    remaining = target_amount

    for bucket in bucket_order:
        entries = loss_buckets[bucket]
        if goal == "min_drift":
            entries.sort(
                key=lambda c: _drift_penalty(c, symbol_weights, target_amount)
            )
        elif goal == "balanced":
            entries.sort(
                key=lambda c: 0.5 * _gain_ratio(c) + 0.5 * _drift_penalty(
                    c, symbol_weights, target_amount
                )
            )
        for cand in entries:
            if remaining <= 0:
                break
            lot = cand["lot"]
            price = cand["price"]
            qty_available = lot.qty
            lot_proceeds = price * qty_available
            qty_to_sell = qty_available
            proceeds = lot_proceeds
            if proceeds > remaining and price > 0:
                qty_to_sell = remaining / price
                proceeds = qty_to_sell * price
            basis = lot.basis_total * (qty_to_sell / lot.qty)
            gain = proceeds - basis
            est_tax, rationale = _estimate_tax_and_rationale(
                gain,
                lot.term,
                tax_rates,
                offsets,
                bucket,
            )

            sell = SellLotRecommendation(
                symbol=lot.symbol,
                lot_id=lot.lot_id,
                acquired_date=lot.acquired_date,
                qty=qty_to_sell,
                price=price,
                proceeds=proceeds,
                basis=basis,
                gain_loss=gain,
                term=lot.term,
                estimated_tax=est_tax,
                rationale=rationale,
            )
            sells.append(sell)
            remaining -= proceeds
        if remaining <= 0:
            break

    if remaining > 0:
        warnings.append("Reached end of tax-efficient candidates before hitting target.")

    return sells, warnings


def _gain_sort_key(cand: Dict) -> Tuple[float, float]:
    lot = cand["lot"]
    proceeds = cand["proceeds"] or 1.0
    gain = cand["gain"]
    ratio = gain / proceeds if proceeds else gain
    return (ratio, gain)


def _gain_ratio(cand: Dict) -> float:
    proceeds = cand["proceeds"] or 1e-6
    gain = cand["gain"]
    return gain / proceeds


def _drift_penalty(cand: Dict, weights: Dict[str, float], target_amount: float) -> float:
    symbol = cand["lot"].symbol
    proceeds = cand["proceeds"]
    if target_amount <= 0:
        return abs(weights.get(symbol, 0.0))
    share = proceeds / target_amount
    return abs(share - weights.get(symbol, 0.0))


def _estimate_tax_and_rationale(
    gain: float,
    term: Term,
    tax_rates: TaxRates,
    offsets: Dict[str, float],
    bucket: str,
) -> Tuple[float, List[str]]:
    rationale: List[str] = []
    if bucket.startswith("loss"):
        rationale.append("Loss lot to offset existing gains")
    else:
        if term == Term.LONG:
            rationale.append("Long-term gain lot (lower rate)")
        else:
            rationale.append("Short-term gain lot (last resort)")

    if gain < 0:
        loss = -gain
        if term == Term.SHORT:
            offset = min(loss, offsets["st"])
            offsets["st"] -= offset
            benefit = offset * (tax_rates.short_term + tax_rates.state)
            carry = loss - offset
            benefit += carry * (
                (tax_rates.short_term + tax_rates.state) * LOSS_CARRY_DISCOUNT
            )
        else:
            offset = min(loss, offsets["lt"])
            offsets["lt"] -= offset
            benefit = offset * (tax_rates.long_term + tax_rates.state)
            carry = loss - offset
            benefit += carry * (
                (tax_rates.long_term + tax_rates.state) * LOSS_CARRY_DISCOUNT
            )
        return -benefit, rationale

    rate = tax_rates.long_term if term == Term.LONG else tax_rates.short_term
    tax = gain * (rate + tax_rates.state)
    return tax, rationale


def _compute_drift_notes(
    holdings: Sequence[Holding],
    sells: Sequence[SellLotRecommendation],
    target_amount: float,
) -> List[str]:
    if not sells or target_amount <= 0:
        return []
    total_value = sum(
        h.market_value if h.market_value is not None else (h.price or 0.0) * h.qty
        for h in holdings
    )
    if not total_value:
        return []
    symbol_weights = {
        h.symbol: (
            h.market_value if h.market_value is not None else (h.price or 0.0) * h.qty
        )
        / total_value
        for h in holdings
    }
    sold = {}
    total_sold = sum(s.proceeds for s in sells)
    if not total_sold:
        return []
    for sell in sells:
        sold[sell.symbol] = sold.get(sell.symbol, 0.0) + sell.proceeds
    notes = []
    for symbol, proceeds in sold.items():
        sell_share = proceeds / total_sold
        target_share = symbol_weights.get(symbol, 0.0)
        drift = sell_share - target_share
        notes.append(
            f"{symbol}: sold {sell_share:.2%} of proceeds vs {target_share:.2%} target (drift {drift:+.2%})"
        )
    return notes


def _symbol_weights(holdings: Sequence[Holding]) -> Dict[str, float]:
    total_value = sum(
        h.market_value if h.market_value is not None else (h.price or 0.0) * h.qty
        for h in holdings
    )
    if not total_value:
        return {}
    return {
        h.symbol: (
            h.market_value if h.market_value is not None else (h.price or 0.0) * h.qty
        )
        / total_value
        for h in holdings
    }


def format_withdrawal_order_csv(proposal: WithdrawalProposal) -> str:
    import csv
    from io import StringIO

    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "Symbol",
            "Action",
            "Qty",
            "Price",
            "Proceeds",
            "Basis",
            "Gain/Loss",
            "Term",
            "Rationale",
        ]
    )
    for sell in proposal.sells:
        writer.writerow(
            [
                sell.symbol,
                "SELL",
                round(sell.qty, 6),
                round(sell.price, 4),
                round(sell.proceeds, 2),
                round(sell.basis, 2),
                round(sell.gain_loss, 2),
                sell.term.value,
                "; ".join(sell.rationale),
            ]
        )
    return buffer.getvalue()
