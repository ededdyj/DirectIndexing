import hashlib
import streamlit as st
import pandas as pd
from datetime import datetime

from src.models import PortfolioDownloadParseResult
from src.parsing.etrade_portfolio_download_parser import (
    build_etrade_template_csv,
    parse_etrade_portfolio_download,
)
from src.parsing.holdings_parser import parse_holdings_csv
from src.parsing.lots_parser import parse_lots_csv
from src.parsing.trades_parser import parse_trades_csv
from src.portfolio.analytics import run_health_checks
from src.portfolio.tlh import identify_candidates
from src.portfolio.replacements import (
    build_replacement_basket,
    infer_sector,
    load_sector_map,
)
from src.portfolio.proposals import build_proposal, export_order_checklist
from src.utils.money import format_currency, format_pct

st.set_page_config(page_title="Direct Indexing TLH MVP", layout="wide")
st.title("Direct Indexing + Tax Loss Harvesting (TLH) MVP")
st.caption(
    "Educational decision-support only. Not investment or tax advice."
)

template_csv = build_etrade_template_csv()

with st.sidebar:
    st.header("Upload data")
    etrade_file = st.file_uploader(
        "E*TRADE Portfolio Download CSV", type="csv"
    )
    st.download_button(
        label="Download template",
        data=template_csv,
        file_name="etrade_portfolio_template.csv",
        mime="text/csv",
    )
    st.caption(
        "Default upload combines holdings + tax lots from the E*TRADE Portfolio Download."
    )
    st.divider()
    st.caption("Optional overrides")
    holdings_file = st.file_uploader("Holdings CSV override", type="csv")
    lots_file = st.file_uploader("Tax Lots CSV override", type="csv")
    trades_file = st.file_uploader("Trades CSV (optional)", type="csv")
    sector_file = st.file_uploader("Sector map (optional)", type="csv")
    st.divider()
    benchmark = st.selectbox("Benchmark target", ["S&P 500", "Total US"])
    loss_threshold = st.number_input(
        "Loss $ threshold", min_value=0.0, value=500.0, step=100.0
    )
    loss_pct_threshold = st.slider(
        "Loss % threshold", min_value=1, max_value=20, value=5
    )
    max_candidates = st.slider("Max candidates", min_value=1, max_value=20, value=10)
    st.write("Benchmark selection stored for context only.")
    st.divider()
    st.warning(
        "Account-only wash sale guard. Trades in other accounts not visible."
    )

holdings = []
lots = []
portfolio_result: PortfolioDownloadParseResult | None = None

if etrade_file:
    try:
        portfolio_result = parse_etrade_portfolio_download(etrade_file)
        holdings = portfolio_result.holdings
        lots = portfolio_result.lots
    except Exception as exc:  # pragma: no cover - UI feedback
        st.error(f"Unable to parse E*TRADE upload: {exc}")
        st.stop()

try:
    if holdings_file:
        holdings = parse_holdings_csv(holdings_file)
    if lots_file:
        lots = parse_lots_csv(lots_file)
    trades = parse_trades_csv(trades_file) if trades_file else []
except Exception as exc:  # pragma: no cover - UI feedback
    st.error(f"Unable to parse uploads: {exc}")
    st.stop()

if not holdings or not lots:
    st.info(
        "Upload the E*TRADE Portfolio Download CSV or provide both holdings and tax lots."
    )
    st.stop()

sector_map = {}
if sector_file:
    try:
        sector_map = load_sector_map(sector_file)
    except Exception as exc:  # pragma: no cover - UI feedback
        st.warning(f"Sector map load failed: {exc}")

if portfolio_result:
    st.subheader("E*TRADE upload summary")
    st.success(portfolio_result.detected_format)
    st.caption(
        "Positions header detected: " + ", ".join(portfolio_result.positions_header)
    )
    if portfolio_result.account_summary:
        summary = portfolio_result.account_summary
        cols = st.columns(3)
        cols[0].metric(
            "Net account value",
            format_currency(summary.net_account_value),
        )
        gain_pct_display = (
            f"{summary.total_gain_pct:.2f}%"
            if summary.total_gain_pct is not None
            else "--"
        )
        cols[1].metric("Total gain %", gain_pct_display)
        cols[2].metric(
            "Cash purchasing power",
            format_currency(summary.cash_purchasing_power),
        )
    if portfolio_result.warnings:
        st.warning("Upload warnings detected:")
        for warn in portfolio_result.warnings:
            st.write("-", warn)

st.subheader("Portfolio snapshots")
col1, col2 = st.columns(2)
col1.dataframe(pd.DataFrame([h.dict() for h in holdings]))
col2.dataframe(pd.DataFrame([l.dict() for l in lots]))

health = run_health_checks(holdings, lots)
issue_entries = []
for category, messages in health.items():
    for message in messages:
        issue_entries.append((category, message))

if issue_entries:
    st.error(
        "Health checks flagged issues. Approve each item to proceed (manual override)."
    )
    approvals = []
    for idx, (category, message) in enumerate(issue_entries):
        label = f"{category.replace('_', ' ').title()}: {message}"
        digest = hashlib.sha1(label.encode("utf-8")).hexdigest()[:8]
        checkbox_key = f"health_issue_{idx}_{digest}"
        approved = st.checkbox(f"Approve: {label}", key=checkbox_key)
        approvals.append(approved)
    if not all(approvals):
        st.stop()
    else:
        st.warning("All health issues approved manually. Proceed with caution.")
else:
    st.success("Data health checks passed. TLH enabled.")

candidates = identify_candidates(
    holdings,
    lots,
    loss_threshold=loss_threshold,
    loss_pct_threshold=loss_pct_threshold / 100,
    max_candidates=max_candidates,
    trades=trades,
)

if not candidates:
    st.info("No TLH candidates match the filters.")
    st.stop()

st.subheader("TLH candidates")

candidate_df = pd.DataFrame(
    [
        {
            "symbol": c.symbol,
            "lot_id": c.lot_id,
            "qty": c.qty,
            "current_value": format_currency(c.current_value),
            "basis_total": format_currency(c.basis_total),
            "unrealized_pl": format_currency(c.unrealized_pl),
            "pl_pct": format_pct(c.pl_pct),
            "term": c.term.value,
            "notes": "; ".join(c.notes),
        }
        for c in candidates
    ]
)
st.dataframe(candidate_df)

candidate_map = {c.lot_id: c for c in candidates}
selected_ids = st.multiselect(
    "Select lots to harvest",
    options=list(candidate_map.keys()),
    format_func=lambda lot_id: f"{candidate_map[lot_id].symbol} | {lot_id}",
)

if not selected_ids:
    st.stop()

selected_candidates = [candidate_map[i] for i in selected_ids]

replacement_plan = {}
for candidate in selected_candidates:
    sector = infer_sector(candidate.symbol, sector_map)
    replacement_plan[candidate.symbol] = build_replacement_basket(
        candidate.symbol,
        sector=sector,
        target_value=candidate.current_value,
    )

proposal = build_proposal(selected_candidates, replacement_plan)

st.subheader("Proposal summary")
st.metric(
    "Expected realized loss",
    format_currency(proposal.expected_realized_loss),
)
if proposal.notes:
    st.write("Notes:")
    for note in proposal.notes:
        st.write("-", note)
if proposal.warnings:
    st.warning("Warnings:")
    for warn in proposal.warnings:
        st.write("-", warn)

checklist_csv = export_order_checklist(proposal)
st.download_button(
    label="Download order checklist CSV",
    data=checklist_csv,
    file_name=f"tlh_order_checklist_{datetime.utcnow().date()}.csv",
    mime="text/csv",
)
