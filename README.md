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

## CSV expectations
All headers are normalized (lowercase, underscores), and common synonyms are mapped automatically. At minimum:

### Holdings CSV
| Required | Optional |
| --- | --- |
| `symbol`, `quantity` | `price`, `market_value` |

### Lots CSV
| Required | Optional |
| --- | --- |
| `symbol`, `acquired_date`, `quantity`, (`cost_basis_total` **or** `cost_basis_per_share`) | `lot_id`, `covered` |

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
