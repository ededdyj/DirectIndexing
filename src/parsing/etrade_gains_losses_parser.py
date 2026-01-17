from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from src.models import GainsLossesParseResult, RealizedGainLossRow, Term
from src.utils.dates import parse_date
from src.utils.money import safe_float
from src.utils.securities import looks_like_symbol

from .common import MissingColumnError, ParsingError, normalize_header


DETAIL_HEADER_CANONICAL = [
    "symbol",
    "quantity",
    "date",
    "cost_share",
    "total_cost",
    "date",
    "price_share",
    "proceeds",
    "gain",
    "deferred_loss",
    "term",
    "lot_selection",
]
STOP_TOKENS = {"generated at", "total"}
ACTION_TOKENS = {"sell", "buy"}


def parse_etrade_gains_losses_csv(source) -> GainsLossesParseResult:
    text = _read_text(source)
    lines = text.splitlines()
    header_idx, header_cells = _find_details_header(lines)
    mapping = _build_column_mapping(header_cells)
    rows, warnings = _parse_detail_rows(lines[header_idx + 1 :], mapping)
    return GainsLossesParseResult(
        rows=rows,
        warnings=warnings,
        header=header_cells,
    )


def _read_text(source) -> str:
    if isinstance(source, (str, Path)):
        return Path(source).read_text(encoding="utf-8-sig")
    data = source.read()
    if hasattr(source, "seek"):
        source.seek(0)
    if isinstance(data, bytes):
        return data.decode("utf-8-sig")
    return str(data)


def _find_details_header(lines: Sequence[str]) -> Tuple[int, List[str]]:
    for idx, line in enumerate(lines):
        if not line.strip():
            continue
        cells = _split_csv_line(line)
        normalized = [_normalize_header_token(cell) for cell in cells]
        if normalized[: len(DETAIL_HEADER_CANONICAL)] == DETAIL_HEADER_CANONICAL:
            return idx, cells
    raise ParsingError("Unable to locate Gains & Losses detail header")


def _build_column_mapping(header_cells: Sequence[str]) -> Dict[str, int]:
    normalized = [_normalize_header_token(cell) for cell in header_cells]
    column_map: Dict[str, int] = {}

    def _require(name: str, candidates: Sequence[str]) -> int:
        for candidate in candidates:
            if candidate in normalized:
                return normalized.index(candidate)
        raise MissingColumnError(f"Missing required column '{name}'")

    column_map["symbol"] = _require("symbol", ["symbol"])
    column_map["quantity"] = _require("quantity", ["quantity", "shares", "qty"])
    date_indices = [idx for idx, label in enumerate(normalized) if label == "date"]
    if len(date_indices) < 2:
        raise MissingColumnError("Expected both acquired and sold date columns")
    column_map["date_acquired"] = date_indices[0]
    column_map["date_sold"] = date_indices[1]

    optional_mapping = {
        "cost_per_share": ["cost_share", "cost_per_share"],
        "cost_basis": ["total_cost", "cost_basis", "cost_basis_total"],
        "price_per_share": ["price_share", "price_per_share"],
        "proceeds": ["proceeds", "amount"],
        "gain": ["gain", "gain_loss", "realized_gain"],
        "deferred_loss": ["deferred_loss", "wash_sale", "wash_sale_disallowed"],
        "term": ["term", "term_description"],
        "lot_selection": ["lot_selection", "method"],
    }

    for key, candidates in optional_mapping.items():
        for candidate in candidates:
            if candidate in normalized:
                column_map[key] = normalized.index(candidate)
                break

    return column_map


def _parse_detail_rows(
    lines: Sequence[str], mapping: Dict[str, int]
) -> Tuple[List[RealizedGainLossRow], List[str]]:
    rows: List[RealizedGainLossRow] = []
    warnings: List[str] = []
    current_symbol: Optional[str] = None
    reader = csv.reader(lines)

    for idx, raw_row in enumerate(reader):
        if not raw_row or not any(cell.strip() for cell in raw_row):
            continue
        symbol_cell = raw_row[mapping["symbol"]].strip()
        lowered = symbol_cell.lower()
        if any(lowered.startswith(token) for token in STOP_TOKENS):
            break
        if lowered.startswith("taxable g&l"):
            continue
        if lowered.startswith("account") or lowered.startswith("filters applied"):
            continue
        if symbol_cell and symbol_cell.lower() == "symbol":
            continue

        is_action_row = lowered in ACTION_TOKENS
        sold_raw = _cell(raw_row, mapping.get("date_sold"))
        effective_symbol: Optional[str] = None

        if is_action_row:
            effective_symbol = current_symbol
        elif sold_raw and sold_raw not in {"", "--"} and looks_like_symbol(symbol_cell):
            effective_symbol = symbol_cell
            current_symbol = effective_symbol.upper()
        else:
            if looks_like_symbol(symbol_cell):
                current_symbol = symbol_cell.upper()
            else:
                warnings.append(f"Unrecognized header row: {symbol_cell}")
            continue

        if not effective_symbol:
            warnings.append("Detail row encountered before symbol header")
            continue

        quantity = safe_float(_cell(raw_row, mapping.get("quantity")), default=None)
        if quantity is None or quantity <= 0:
            warnings.append(f"Skipping row for {effective_symbol}: invalid quantity")
            continue

        acquired = _parse_optional_date(_cell(raw_row, mapping.get("date_acquired")))
        sold_text = _cell(raw_row, mapping.get("date_sold"))
        try:
            sold_date = parse_date(sold_text)
        except Exception:
            warnings.append(
                f"Skipping row for {effective_symbol}: invalid sold date '{sold_text}'"
            )
            continue

        proceeds = safe_float(_cell(raw_row, mapping.get("proceeds")), default=None)
        cost_basis = safe_float(_cell(raw_row, mapping.get("cost_basis")), default=None)
        gain_value = safe_float(_cell(raw_row, mapping.get("gain")), default=None)
        if gain_value is None and proceeds is not None and cost_basis is not None:
            gain_value = proceeds - cost_basis
        if gain_value is None:
            warnings.append(f"Missing gain data for {effective_symbol} on {sold_text}")
            continue

        deferred_loss = safe_float(
            _cell(raw_row, mapping.get("deferred_loss")), default=None
        )
        term_text = _cell(raw_row, mapping.get("term"))
        term_value = _normalize_term(term_text)

        row = RealizedGainLossRow(
            symbol=effective_symbol,
            quantity=quantity,
            date_acquired=acquired,
            date_sold=sold_date,
            proceeds=proceeds,
            cost_basis=cost_basis,
            realized_gain_loss=gain_value,
            term=term_value,
            wash_sale_disallowed=deferred_loss,
            source_row_id=f"{effective_symbol}_{sold_date.isoformat()}_{idx}",
        )
        rows.append(row)

    return rows, warnings


def _cell(row: Sequence[str], index: Optional[int]) -> str:
    if index is None or index >= len(row):
        return ""
    return row[index].strip()


def _normalize_header_token(token: str) -> str:
    return normalize_header(token).replace("__", "_")


def _parse_optional_date(value: str) -> Optional[date]:
    if not value or value == "--":
        return None
    try:
        return parse_date(value)
    except Exception:
        return None


def _normalize_term(value: str) -> Term:
    if not value:
        return Term.UNKNOWN
    text = value.strip().lower()
    if text.startswith("short"):
        return Term.SHORT
    if text.startswith("long"):
        return Term.LONG
    return Term.UNKNOWN


def _split_csv_line(line: str) -> List[str]:
    return next(csv.reader([line]))
