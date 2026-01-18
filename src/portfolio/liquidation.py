from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from src.models import Holding, Lot, RealizedSummary, SellLotRecommendation, Term
from src.portfolio.analytics import price_lookup
from src.utils.securities import is_money_market_symbol

DEFAULT_SHORT_TERM_RATE = 0.32
DEFAULT_LONG_TERM_RATE = 0.15
DEFAULT_STATE_RATE = 0.05
LOSS_CARRY_DISCOUNT = 0.5


@dataclass
class TaxRates:
    short_term: float = DEFAULT_SHORT_TERM_RATE
    long_term: float = DEFAULT_LONG_TERM_RATE
    state: float = DEFAULT_STATE_RATE


def estimate_available_cash(
    holdings: Iterable[Holding],
    manual_cash: float = 0.0,
    include_cash_equivalents: bool = True,
) -> float:
    cash = manual_cash
    if not include_cash_equivalents:
        return cash
    for holding in holdings:
        if getattr(holding, "is_cash_equivalent", False):
            if holding.market_value is not None:
                cash += holding.market_value
            elif holding.price is not None:
                cash += holding.price * holding.qty
    return cash


def build_sell_candidates(
    lots: Iterable[Lot],
    holdings: Optional[Iterable[Holding]],
    exclude_symbols: Sequence[str],
    exclude_missing_dates: bool,
) -> Tuple[List[Dict], List[str]]:
    price_map = price_lookup(list(holdings or []))
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
        candidates.append(
            {
                "lot": lot,
                "price": price,
                "proceeds": price * lot.qty,
                "gain": price * lot.qty - lot.basis_total,
            }
        )
    return candidates, warnings


def compute_symbol_weights(holdings: Sequence[Holding]) -> Dict[str, float]:
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


def select_sells(
    candidates: List[Dict],
    target_amount: float,
    summary: RealizedSummary,
    tax_rates: TaxRates,
    goal: str,
    symbol_weight: Dict[str, float],
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
            key = "loss_st" if lot.term == Term.SHORT else "loss_lt"
        else:
            key = "gain_lt" if lot.term == Term.LONG else "gain_st"
        loss_buckets[key].append(cand)

    loss_buckets["loss_st"].sort(key=lambda c: c["gain"])
    loss_buckets["loss_lt"].sort(key=lambda c: c["gain"])
    loss_buckets["gain_lt"].sort(key=_gain_sort_key)
    loss_buckets["gain_st"].sort(key=_gain_sort_key)

    bucket_order = ["loss_st", "loss_lt", "gain_lt", "gain_st"]
    offsets = {
        "st": max(0.0, summary.ytd_realized_st),
        "lt": max(0.0, summary.ytd_realized_lt),
    }
    remaining = target_amount

    for bucket in bucket_order:
        entries = loss_buckets[bucket]
        if goal == "min_drift":
            entries.sort(key=lambda c: _drift_penalty(c, symbol_weight, target_amount))
        elif goal == "balanced":
            entries.sort(
                key=lambda c: 0.5 * _gain_ratio(c)
                + 0.5 * _drift_penalty(c, symbol_weight, target_amount)
            )
        for cand in entries:
            if remaining <= 0:
                break
            lot = cand["lot"]
            price = cand["price"]
            qty_available = lot.qty
            proceeds = price * qty_available
            qty_to_sell = qty_available
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
            sells.append(
                SellLotRecommendation(
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
            )
            remaining -= proceeds
        if remaining <= 0:
            break

    if remaining > 0:
        warnings.append("Reached end of candidates before hitting target.")

    return sells, warnings


def _gain_sort_key(cand: Dict) -> Tuple[float, float]:
    proceeds = cand["proceeds"] or 1.0
    gain = cand["gain"]
    ratio = gain / proceeds if proceeds else gain
    return (ratio, gain)


def _gain_ratio(cand: Dict) -> float:
    proceeds = cand["proceeds"] or 1e-8
    return cand["gain"] / proceeds


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
        rationale.append("Loss lot offsets realized gains")
    else:
        rationale.append("Long-term gain lot" if term == Term.LONG else "Short-term gain lot")

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


def compute_drift_notes(
    holdings: Sequence[Holding], sells: Sequence[SellLotRecommendation], target_amount: float
) -> List[str]:
    if not sells or target_amount <= 0:
        return []
    total_value = sum(
        h.market_value if h.market_value is not None else (h.price or 0.0) * h.qty
        for h in holdings
    )
    if not total_value:
        return []
    weights = compute_symbol_weights(holdings)
    sold_totals: Dict[str, float] = {}
    total_sold = sum(s.proceeds for s in sells)
    if not total_sold:
        return []
    for sell in sells:
        sold_totals[sell.symbol] = sold_totals.get(sell.symbol, 0.0) + sell.proceeds
    notes = []
    for symbol, proceeds in sold_totals.items():
        sell_share = proceeds / total_sold
        target_share = weights.get(symbol, 0.0)
        drift = sell_share - target_share
        notes.append(
            f"{symbol}: sold {sell_share:.2%} vs {target_share:.2%} weight (drift {drift:+.2%})"
        )
    return notes


def format_sells_csv(sells: Sequence[SellLotRecommendation]) -> str:
    from io import StringIO
    import csv

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
    for sell in sells:
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
