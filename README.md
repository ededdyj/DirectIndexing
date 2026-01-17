# Direct Indexing + TLH MVP

A local Streamlit application that ingests exported E*TRADE CSV files, normalizes holdings and tax lots, surfaces conservative tax-loss harvesting (TLH) candidates, proposes replacement baskets, and exports a manual order checklist. This v0.1 release is educational decision-support only—no broker APIs or trade execution.

## What it does
- Upload holdings, lot, optional trades, and optional sector mapping CSVs.
- Normalize messy headers and validate data integrity (missing basis, lot/holding quantity gaps).
- Score TLH candidates with configurable dollar/percentage thresholds, short-term preference, near long-term warnings, and account-level wash-sale hints using recent buy trades.
- Generate replacement baskets (sector-aware if mapping is provided, else generic mega-cap ETFs) and summarize proposals.
- Export a CSV checklist for manual E*TRADE order entry.

## What it does **not** do
- No trade execution, broker APIs, or automated order routing.
- No visibility into other taxable/brokerage accounts for wash-sale protection.
- Does not provide tax advice; consult a qualified professional before acting.

## Safety + disclaimers
- Wash-sale guard is account-only and depends on the provided Trades CSV. Buys in other accounts (or future trades) are not captured.
- If any tax lot is missing cost basis or holdings vs. lots quantities diverge beyond tolerance, TLH actions are disabled until the data is fixed.
- Replacement basket suggestions are placeholders; confirm suitability and liquidity before trading.

## Installation
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running the Streamlit app
```bash
streamlit run app.py
```
The app opens in your browser. Use the sidebar to upload CSVs and adjust TLH thresholds. Download the generated order checklist once satisfied.

## E*TRADE Portfolio Download (PositionsSimple) Upload Support
- Upload the raw E*TRADE `PortfolioDownload-*.csv` export directly (Account Summary + View Summary - PositionsSimple in one file). The parser scans for the table header `Symbol,Qty #,Value $,Total Cost`, normalizes position rows, and associates any indented lot rows underneath each symbol.
- **Account Summary** rows are optional but, when present, the app surfaces metrics for account value, gain %, and cash purchasing power.
- **Required columns** in the PositionsSimple table: `Symbol`, `Qty #`, `Value $`, `Total Cost`. Extra columns are ignored. `Symbol` rows create `Holding` records (qty, market value, optional inferred price and total cost basis).
- **Lot rows** are identified by a blank/whitespace symbol column followed by an acquired date (`MM/DD/YYYY` or similar) or `--`. Parsed lots require: symbol inherited from the parent position, acquired date, quantity, and total cost basis. The `Value $` column is optional but, when populated, yields optional `current_value` and `current_price` fields.
- **Normalization + derivations**:
  - `symbol`: uppercase equity tickers only (`[A-Z]{1,5}` with optional `.XX`). Non-equity identifiers (CUSIPs, notes, etc.) are skipped and reported as warnings.
  - `acquired_date`: parsed using several common formats; `--` rows are excluded with a warning.
  - `lot_qty`: numeric parser handles commas, `$`, and parentheses. `qty <= 0` rows become warnings.
  - `cost_basis_total`: taken from `Total Cost` when present; otherwise, the parser attempts to use lot value as a fallback. If both are missing the lot is rejected.
  - `current_price` / `current_value`: derived from `Value $` when present; otherwise left `None`.
- **Missing columns / health checks**: the parser and downstream checks flag missing required headers, absent acquired dates, non-numeric quantities/basis, or impossible dates. The existing holdings-vs-lots quantity reconciliation remains enforced before TLH.
- **Template export**: the sidebar offers a sanitized sample export (header + example rows) so other E*TRADE users can confirm the structure before uploading real data.
- **Fallback uploads**: advanced users may still upload separate Holdings + Tax Lots CSVs; these override the combined file when provided.
- **Cash equivalents**: common money-market tickers (e.g., `VMFXX`, `SPRXX`) are auto-tagged as cash equivalents. They remain visible in the holdings table but are ignored for lot/holding mismatch checks and TLH targeting.

## E*TRADE Gains & Losses CSV Support
- Upload the `GainsAndLossesDowload.csv` export from the E*TRADE “Gains & Losses” tab. The parser skips the summary section, finds the `Symbol,Quantity,Date,...` table, and associates indented `Sell` rows with the preceding symbol header.
- **Required columns** (case/spacing agnostic): `Symbol`, `Quantity`, two `Date` columns (acquired/sold), `Total Cost $`, `Proceeds $`, `Gain $`, `Term`. Optional inputs include `Cost/Share $`, `Price/Share $`, `Deferred Loss $` (used for wash-sale disallowances), and `Lot Selection`.
- Numeric parsing tolerates commas, `$`, blank cells, and parentheses for negatives; `--` is treated as missing.
- Summary rows such as `Total` or `Generated at` are ignored automatically.
- Parsed rows become `RealizedGainLossRow` instances feeding a `RealizedSummary` (YTD realized ST/LT totals, net wash-sale disallowed amounts, row counts, and warnings).
- The TLH workflow uses this tax context to rank candidates (prioritizing short-term losses when short-term gains exist), surface wash-sale adjustments, and compute a “loss budget” when the user selects **Offset realized gains**.
- If the report is not uploaded the UI shows a banner and assumes $0 realized gains—recommendations will still run but are more conservative.

## Health check overrides & cash equivalents
- The TLH workflow still runs the existing data health checks (lot basis coverage and holdings-vs-lots reconciliation). When issues are detected, each item must be explicitly approved via sidebar checkboxes before TLH results are shown—making it clear that the user is proceeding with known data caveats.
- Money-market holdings are flagged as cash equivalents, excluded from lot-matching requirements, and treated as cash in downstream analytics. This prevents cash sweep funds (VMFXX, SPAXX, etc.) from blocking TLH analysis.
- The sidebar now includes a “Goal for TLH this year” control. Choosing **Offset realized gains** activates a loss target equal to the net positive gains in the uploaded report; the app stops suggesting new lots once the projected losses meet that budget (within tolerance). Selecting **Harvest opportunistically** bypasses the target and simply surfaces the best remaining loss opportunities.

## CSV expectations
All headers are normalized (lowercase, underscores), and common synonyms are mapped automatically. The tables below describe the fallback single-table uploads; prefer the combined E*TRADE Portfolio Download format when possible.

### Holdings CSV
| Required | Optional |
| --- | --- |
| `symbol`, `quantity` | `price`, `market_value` |

### Lots CSV
| Required | Optional |
| --- | --- |
| `symbol`, `acquired_date`, `quantity`, (`cost_basis_total` **or** `cost_basis_per_share`) | `lot_id`, `covered` |

### Gains & Losses CSV (optional but recommended)
| Required | Optional |
| --- | --- |
| `symbol`, `quantity`, `date_acquired`, `date_sold`, `total_cost`, `proceeds`, `gain`, `term` | `cost_per_share`, `price_per_share`, `deferred_loss`, `lot_selection` |

### Trades CSV (optional)
| Required |
| --- |
| `symbol`, `trade_date`, `quantity`, `side` |

### Sector map CSV (optional)
| Required |
| --- |
| `symbol`, `sector` |

All CSVs may include additional columns. Sample files live under `sample_data/`.

## Tests
Run unit tests with pytest:
```bash
pytest
```

## Sample data
- `sample_data/holdings_example.csv`
- `sample_data/lots_example.csv`
- `sample_data/trades_example.csv`

Use these as templates for formatting, not as real data.

## Changelog
- **2026-01-17** Added native support for E*TRADE Portfolio Download (PositionsSimple) exports, Gains & Losses uploads, tax-context driven TLH goals, manual health-check overrides, and money-market detection for cash equivalents.
