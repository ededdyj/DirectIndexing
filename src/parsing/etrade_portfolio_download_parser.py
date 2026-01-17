from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
import re
from typing import Iterable, List, Optional, Sequence, Tuple, Union

from src.models import (
    AccountSummary,
    Holding,
    Lot,
    PortfolioDownloadParseResult,
)
from src.utils.dates import parse_date
from src.utils.money import safe_float

from .common import ParsingError


ACCOUNT_SUMMARY_MARKER = "account summary"
POSITIONS_HEADER = "symbol,qty #,value $,total cost"
EQUITY_SYMBOL_PATTERN = re.compile(r"^[A-Z]{1,5}(?:\.[A-Z]{1,2})?$")


def parse_etrade_portfolio_download(source) -> PortfolioDownloadParseResult:
    """Parse combined holdings + lots from an E*TRADE Portfolio Download CSV."""

    text = _read_text(source)
    lines = text.splitlines()
    account_summary = _parse_account_summary(lines)
    header_idx, header_cells = _find_positions_header(lines)
    holdings, lots, warnings = _parse_positions(lines[header_idx + 1 :])

    return PortfolioDownloadParseResult(
        holdings=holdings,
        lots=lots,
        warnings=warnings,
        positions_header=header_cells,
        account_summary=account_summary,
    )


def build_etrade_template_csv() -> str:
    """Return a sanitized template mimicking the Portfolio Download format."""

    template_lines = [
        "Account Summary",
        "Account,Net Account Value,Total Gain $,Total Gain %,Day's Gain Unrealized $,Day's Gain Unrealized %,Available For Withdrawal,Cash Purchasing Power",
        '"Sample Brokerage -0001",100000.00,5000.00,5.00,150.00,0.15,90000.00,45000.00',
        "",
        "View Summary - PositionsSimple",
        "Filters applied:",
        "Symbol,Security type(s),Sort by,Sort order,",
        ",All,Symbol,Asc,",
        "",
        "Symbol,Qty #,Value $,Total Cost",
        "AAA,100.0000,1500.0000,1200.0000",
        "     01/15/2022,40.0000,600.0000,480.0000",
        "     03/10/2023,60.0000,900.0000,720.0000",
    ]
    return "\n".join(template_lines)


def _read_text(source) -> str:
    if isinstance(source, (str, Path)):
        return Path(source).read_text(encoding="utf-8-sig")
    data = source.read()
    if hasattr(source, "seek"):
        source.seek(0)
    if isinstance(data, bytes):
        return data.decode("utf-8-sig")
    return str(data)


def _parse_account_summary(lines: Sequence[str]) -> Optional[AccountSummary]:
    marker_idx = None
    for idx, line in enumerate(lines):
        if line.strip().lower() == ACCOUNT_SUMMARY_MARKER:
            marker_idx = idx
            break
    if marker_idx is None:
        return None

    header_line = _next_nonempty_line(lines, marker_idx + 1)
    data_line = _next_nonempty_line(lines, marker_idx + 2)
    if not header_line or not data_line:
        return None
    data_cells = _split_csv_line(data_line)
    sanitized = [cell.strip().strip('"') for cell in data_cells]

    field_parsers: List[Tuple[str, Optional[bool]]] = [
        ("account", None),
        ("net_account_value", True),
        ("total_gain_amount", True),
        ("total_gain_pct", True),
        ("days_gain_amount", True),
        ("days_gain_pct", True),
        ("available_for_withdrawal", True),
        ("cash_purchasing_power", True),
    ]

    kwargs = {}
    for idx, (field, numeric) in enumerate(field_parsers):
        if idx >= len(sanitized):
            break
        raw = sanitized[idx]
        if numeric:
            kwargs[field] = safe_float(raw, default=None)
        else:
            kwargs[field] = raw
    if "account" not in kwargs or not kwargs["account"]:
        return None
    return AccountSummary(**kwargs)


def _find_positions_header(lines: Sequence[str]) -> Tuple[int, List[str]]:
    for idx, line in enumerate(lines):
        if line.strip().lower() == POSITIONS_HEADER:
            header_cells = [cell.strip() for cell in _split_csv_line(line)]
            return idx, header_cells
    raise ParsingError("Unable to locate PositionsSimple header in file")


def _parse_positions(lines: Sequence[str]) -> Tuple[List[Holding], List[Lot], List[str]]:
    holdings: List[Holding] = []
    lots: List[Lot] = []
    warnings: List[str] = []
    current_symbol: Optional[str] = None
    lot_sequence = defaultdict(int)

    reader = csv.reader(lines)
    for row in reader:
        if not row:
            continue
        if not any(cell.strip() for cell in row):
            break

        first_cell = row[0].strip()
        if _looks_like_symbol(first_cell):
            symbol = first_cell.upper()
            if not _is_equity_symbol(symbol):
                warnings.append(f"Skipped non-equity position '{symbol}'")
                current_symbol = None
                continue
            qty = safe_float(row[1] if len(row) > 1 else None, default=None)
            if qty is None or qty <= 0:
                warnings.append(f"Invalid quantity for symbol '{symbol}'")
                current_symbol = symbol
                continue
            market_value = safe_float(row[2] if len(row) > 2 else None, default=None)
            cost_basis = safe_float(row[3] if len(row) > 3 else None, default=None)
            price = None
            if market_value is not None and qty:
                price = market_value / qty
            holding = Holding(
                symbol=symbol,
                qty=qty,
                price=price,
                market_value=market_value,
                cost_basis_total=cost_basis,
            )
            holdings.append(holding)
            current_symbol = symbol
            continue

        lot = _parse_lot_row(row, current_symbol, lot_sequence)
        if isinstance(lot, Lot):
            lots.append(lot)
        elif lot:  # warning message
            warnings.append(lot)

    return holdings, lots, warnings


def _parse_lot_row(
    row: Sequence[str],
    current_symbol: Optional[str],
    lot_sequence,
) -> Union[Lot, str, None]:
    if not current_symbol:
        if any(cell.strip() for cell in row):
            return "Lot row encountered before a symbol row"
        return None

    shifted = _shift_lot_columns(row)
    if shifted is None:
        return f"Unrecognized lot row for '{current_symbol}'"
    date_text, qty_idx, value_idx, cost_idx = shifted
    date_text = date_text.strip()

    if date_text == "--" or not date_text:
        return f"Lot for {current_symbol} missing acquired date"
    try:
        acquired_date = parse_date(date_text)
    except ValueError:
        return f"Unsupported date '{date_text}' for {current_symbol}"

    qty = safe_float(row[qty_idx] if len(row) > qty_idx else None, default=None)
    if qty is None or qty <= 0:
        return f"Invalid quantity for lot {current_symbol} on {date_text}"
    value = safe_float(row[value_idx] if len(row) > value_idx else None, default=None)
    basis_total = safe_float(row[cost_idx] if len(row) > cost_idx else None, default=None)
    if basis_total is None:
        if value is not None:
            basis_total = value
        else:
            return f"Missing cost basis for {current_symbol} lot on {date_text}"

    lot_sequence[current_symbol] += 1
    lot_id = f"{current_symbol}_{acquired_date.isoformat()}_{lot_sequence[current_symbol]}"
    current_price = None
    if value is not None and qty:
        current_price = value / qty

    return Lot(
        lot_id=lot_id,
        symbol=current_symbol,
        acquired_date=acquired_date,
        qty=qty,
        basis_total=basis_total,
        current_value=value,
        current_price=current_price,
    )


def _shift_lot_columns(row: Sequence[str]) -> Optional[Tuple[str, int, int, int]]:
    if not row:
        return None
    first = row[0].strip()
    if _looks_like_date(first):
        return first, 1, 2, 3
    if len(row) > 1 and _looks_like_date(row[1].strip()):
        return row[1].strip(), 2, 3, 4
    return None


def _looks_like_date(value: str) -> bool:
    if not value:
        return False
    text = value.strip()
    if text == "--":
        return True
    has_sep = any(sep in text for sep in ("/", "-"))
    digits = sum(ch.isdigit() for ch in text)
    return has_sep and digits >= 6


def _looks_like_symbol(value: str) -> bool:
    if not value:
        return False
    text = value.strip().upper()
    return bool(text) and not _looks_like_date(text)


def _is_equity_symbol(value: str) -> bool:
    return bool(EQUITY_SYMBOL_PATTERN.fullmatch(value.strip().upper()))


def _split_csv_line(line: str) -> List[str]:
    return next(csv.reader([line]))


def _next_nonempty_line(lines: Sequence[str], start: int) -> Optional[str]:
    for idx in range(start, len(lines)):
        if lines[idx].strip():
            return lines[idx]
    return None
