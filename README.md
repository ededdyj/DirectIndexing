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

## Withdrawal Planner
- The new Withdrawal Planner tab helps raise cash for withdrawals in a tax-aware, benchmark-aware way. Provide a withdrawal dollar target, optional cash buffer, and (if needed) manual cash already available; the planner uses cash equivalents first and only recommends sells when necessary.
- **Best-practice ordering:** lots are evaluated using a MinTax-inspired hierarchy—short-term loss lots first, then long-term losses, then long-term gains (highest basis first), and finally short-term gains as a last resort. Specific lots are selected to minimize estimated tax cost while preserving exposures.
- **Tax context integration:** if the Gains & Losses CSV is uploaded, the planner knows current ST/LT gains and prioritizes harvesting losses to offset the highest-rate gains. Without the report, it assumes $0 realized gains and displays a warning that tax impact is approximate.
- **Portfolio drift guardrails:** sells are compared against each holding’s weight; optional liquidation goals let users minimize taxes, minimize benchmark drift, or take a balanced approach. Drift metrics are reported alongside the recommendations.
- **Explainability and export:** every recommended lot shows proceeds, basis, gain/loss, estimated tax, and rationale (“loss lot to offset gains,” “long-term gain lot,” etc.). The “Why these sells?” panel summarizes the ordering logic and drift results, and users can export a sell-only order checklist CSV for manual execution.

## Direct Indexing Strategy Builder
- The Strategy Builder tab lets you design a benchmark-tracking basket using starter universes stored under `data/universes/` (S&P 500, Total US, Nasdaq 100). Each CSV contains a symbol column, normalized weights, and optional sector labels—no external APIs required.
- Screens and exclusions are applied deterministically: toggle built-in lists for Oil & Gas, Tobacco, and Weapons (sample symbol files under `data/screens/`), specify tickers to exclude, and optionally paste comma-separated tickers. After filtering, weights are capped at the chosen single-name limit, renormalized, and trimmed to the requested holdings count.
- Cash equivalents (VMFXX, SPRXX, etc.) are omitted by default so the target basket is fully invested; you can opt to include them when designing cash-plus strategies.
- Outputs include a sortable table with target weights, sector tags (from the universe or your uploaded sector map), summary metrics (holdings count, top-10 concentration, max weight), and warnings whenever filters remove too much of the index. Download both the basket (`target_basket.csv`) and the underlying `strategy.json` for reuse; uploaders let you reload either artifact later.
- Universe CSVs under `data/universes/` are refreshed via `scripts/update_universes.py`, which sources holdings directly from iShares IVV (S&P 500), ITOT (Total US), and Slickcharts/Wikipedia (Nasdaq-100 weights with sector mapping). The script validates schema + unit weights before saving.
- Limitations: universes and screen lists are illustrative starters, not comprehensive index constituents. Update the CSVs as needed for production coverage.

## Strategy Allocation + Transition Planner
- Once a strategy is defined, the “Allocate & Transition” tab turns that target basket into an actionable plan. Provide an allocation dollar amount, optional cash buffer (percentage or dollar override), and cash-on-hand inputs.
- Cash equivalents are applied first (unless disabled) so that only the shortfall is funded through tax-aware sells. The existing MinTax ordering (ST losses → LT losses → LT gains → ST gains) is reused, layered with optional drift-aware penalties and user-provided exclusions. Realized gains context from the Gains & Losses CSV is honored, prioritizing offsets for high-rate ST gains.
- Buy targets convert basket weights into dollar allocations (and estimated shares when prices are available from current holdings). Any symbols lacking prices are surfaced with warnings instead of silent assumptions.
- Explainability is built-in: funding summaries show cash used vs. needed, lot-level sell tables include rationale + estimated tax, buy targets list target dollars/shares, and the “Why this plan?” panel cites the sequencing logic, realized-gain context, drift notes, and any data warnings. Export ready-to-share files: `sell_checklist_transition.csv`, `buy_targets_transition.csv`, and a human-readable `transition_summary.txt`.

## Plan Narratives (Explainability)
- Every tab that produces a plan (TLH, Withdrawal, Transition, Manage Strategy) now offers a “Generate narrative” button. Narratives are deterministic, rule-based summaries (no AI text generation) that spell out goals, trade selection logic (e.g., MinTax ordering, replacement selection, drift tolerances), estimated tax impacts, and explicit warnings about assumptions (missing Gains & Losses file, health-check overrides, wash-sale caveats).
- Downloadable `narrative.txt` and `narrative.json` files help document the rationale for manual review or compliance records. Remember: narratives are educational decision-support only—not tax or investment advice.

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
- **2026-01-17** Added native support for E*TRADE Portfolio Download (PositionsSimple) exports, Gains & Losses uploads, tax-context driven TLH goals, manual health-check overrides, money-market detection for cash equivalents, and the Withdrawal Planner (tax-aware liquidation).
