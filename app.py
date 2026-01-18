import hashlib
import streamlit as st
import pandas as pd
from datetime import datetime

from src.models import (
    PortfolioDownloadParseResult,
    RealizedSummary,
    StrategyAllocationRequest,
    StrategySpec,
    TaxRateInput,
)
from src.parsing.etrade_gains_losses_parser import parse_etrade_gains_losses_csv
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
from src.portfolio.withdrawals import (
    TaxRates,
    build_withdrawal_proposal,
    format_withdrawal_order_csv,
)
from src.portfolio.strategy import (
    build_target_basket,
    export_basket_csv,
    load_universe,
)
from src.portfolio.transition import (
    build_transition_plan,
    format_buy_targets_csv,
    format_transition_summary,
)
from src.portfolio.liquidation import format_sells_csv
from src.portfolio.tax_context import (
    GOAL_OFFSET_GAINS,
    GOAL_OPPORTUNISTIC,
    compute_loss_target,
    summarize_realized,
)
from src.utils.money import format_currency, format_pct

st.set_page_config(page_title="Direct Indexing TLH MVP", layout="wide")
st.title("Direct Indexing + Tax Loss Harvesting (TLH) MVP")
st.caption(
    "Educational decision-support only. Not investment or tax advice."
)

template_csv = build_etrade_template_csv()
goal_labels = {
    GOAL_OFFSET_GAINS: "Offset realized gains (recommended if you have gains)",
    GOAL_OPPORTUNISTIC: "Harvest opportunistically (build carryforward)",
}
goal_options = list(goal_labels.keys())

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
    gains_file = st.file_uploader(
        "E*TRADE Gains & Losses CSV (optional)", type="csv"
    )
    st.caption("Add realized gains to tailor TLH targets.")
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
    default_goal = GOAL_OFFSET_GAINS if gains_file else GOAL_OPPORTUNISTIC
    default_index = goal_options.index(default_goal)
    tlh_goal = st.selectbox(
        "Goal for TLH this year",
        options=goal_options,
        format_func=lambda key: goal_labels[key],
        index=default_index,
    )
    st.write("Benchmark selection stored for context only.")
    st.divider()
    st.warning(
        "Account-only wash sale guard. Trades in other accounts not visible."
    )

holdings = []
lots = []
portfolio_result: PortfolioDownloadParseResult | None = None
realized_summary: RealizedSummary | None = None
missing_gains_report = False

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

gains_result = None
if gains_file:
    try:
        gains_result = parse_etrade_gains_losses_csv(gains_file)
        realized_summary = summarize_realized(
            gains_result.rows, warnings=gains_result.warnings
        )
    except Exception as exc:  # pragma: no cover - UI feedback
        st.warning(f"Gains & Losses parsing failed: {exc}")

if realized_summary is None:
    missing_gains_report = True
    realized_summary = RealizedSummary()
else:
    missing_gains_report = False

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

st.subheader("Tax context")
if missing_gains_report:
    st.warning(
        "Realized gains/losses file not uploaded — TLH recommendations assume $0 realized gains YTD."
    )
tax_cols = st.columns(3)
tax_cols[0].metric(
    "YTD ST realized",
    format_currency(realized_summary.ytd_realized_st),
)
tax_cols[1].metric(
    "YTD LT realized",
    format_currency(realized_summary.ytd_realized_lt),
)
tax_cols[2].metric(
    "Wash-sale disallowed",
    format_currency(realized_summary.ytd_wash_sale_disallowed_total),
)
if realized_summary.warnings:
    for warn in realized_summary.warnings:
        st.info(warn)

loss_target_value = compute_loss_target(realized_summary, tlh_goal)
if tlh_goal == GOAL_OFFSET_GAINS:
    st.caption(
        f"Loss budget needed to offset gains: {format_currency(loss_target_value)}"
    )
else:
    st.caption("Harvesting opportunistically; no explicit loss target.")

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

tlh_tab, withdrawal_tab, strategy_tab, transition_tab = st.tabs(
    ["TLH Engine", "Withdrawal Planner", "Strategy Builder", "Allocate & Transition"]
)

with tlh_tab:
    st.subheader("TLH candidates")
    candidates = identify_candidates(
        holdings,
        lots,
        loss_threshold=loss_threshold,
        loss_pct_threshold=loss_pct_threshold / 100,
        max_candidates=max_candidates,
        trades=trades,
        realized_summary=realized_summary,
        tlh_goal=tlh_goal,
        loss_target=loss_target_value,
    )

    if not candidates:
        st.info("No TLH candidates match the filters.")
    else:
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
            key="tlh_selection",
        )

        if not selected_ids:
            st.info("Select at least one lot to build an order checklist.")
        else:
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

with withdrawal_tab:
    st.subheader("Withdrawal Planner")
    withdrawal_amount = st.number_input(
        "Withdrawal amount ($)", min_value=0.0, value=0.0, step=100.0
    )
    buffer_pct = (
        st.number_input("Cash buffer (%)", min_value=0.0, value=1.0, step=0.5) / 100.0
    )
    manual_cash = st.number_input(
        "Additional cash available ($)", min_value=0.0, value=0.0, step=100.0
    )

    st.markdown("**Tax rate assumptions**")
    tax_cols = st.columns(3)
    st_rate = tax_cols[0].number_input(
        "Short-term marginal rate (%)", min_value=0.0, max_value=70.0, value=32.0
    )
    lt_rate = tax_cols[1].number_input(
        "Long-term capital gains rate (%)", min_value=0.0, max_value=50.0, value=15.0
    )
    state_rate = tax_cols[2].number_input(
        "State tax rate (%)", min_value=0.0, max_value=20.0, value=5.0
    )

    goal_map = {
        "Minimize taxes (default)": "min_tax",
        "Balanced": "balanced",
        "Minimize drift to benchmark": "min_drift",
    }
    goal_choice = st.selectbox(
        "Liquidation goal",
        options=list(goal_map.keys()),
        index=0,
    )
    exclude_symbols = st.multiselect(
        "Exclude symbols from selling",
        options=sorted({h.symbol for h in holdings}),
    )
    exclude_missing_dates = st.checkbox(
        "Exclude lots with missing acquired date (--)", value=True
    )

    if withdrawal_amount <= 0:
        st.info("Enter a withdrawal amount to generate recommendations.")
    else:
        tax_rates = TaxRates(
            short_term=st_rate / 100.0,
            long_term=lt_rate / 100.0,
            state=state_rate / 100.0,
        )
        proposal = build_withdrawal_proposal(
            holdings,
            lots,
            realized_summary,
            withdrawal_amount=withdrawal_amount,
            cushion_pct=buffer_pct,
            manual_cash=manual_cash,
            tax_rates=tax_rates,
            goal=goal_map[goal_choice],
            exclude_symbols=exclude_symbols,
            exclude_missing_dates=exclude_missing_dates,
        )

        summary_cols = st.columns(3)
        summary_cols[0].metric(
            "Cash available",
            format_currency(proposal.cash_available),
        )
        summary_cols[1].metric(
            "Needed from sells",
            format_currency(proposal.amount_needed_from_sales),
        )
        summary_cols[2].metric(
            "Estimated tax cost",
            format_currency(proposal.estimated_tax_cost),
        )

        st.metric(
            "Expected proceeds",
            format_currency(proposal.total_expected_proceeds),
        )
        st.metric(
            "Est. ST realized",
            format_currency(proposal.estimated_realized_st),
        )
        st.metric(
            "Est. LT realized",
            format_currency(proposal.estimated_realized_lt),
        )

        if proposal.warnings:
            st.warning("Withdrawal warnings:")
            for warn in proposal.warnings:
                st.write("-", warn)

        if not proposal.sells:
            st.info("No sale recommendations needed given inputs.")
        else:
            sell_df = pd.DataFrame(
                [
                    {
                        "symbol": sell.symbol,
                        "lot_id": sell.lot_id,
                        "acquired_date": sell.acquired_date,
                        "qty": sell.qty,
                        "price": sell.price,
                        "proceeds": sell.proceeds,
                        "basis": sell.basis,
                        "gain_loss": sell.gain_loss,
                        "term": sell.term.value,
                        "estimated_tax": sell.estimated_tax,
                        "rationale": "; ".join(sell.rationale),
                    }
                    for sell in proposal.sells
                ]
            )
            st.dataframe(sell_df)

            with st.expander("Why these sells?"):
                st.write(
                    "Loss lots (short-term first, then long-term) are prioritized to offset current gains."
                )
                st.write(
                    "Long-term gain lots are next because of preferential rates, while short-term gains are last resort."
                )
                if proposal.drift_metrics:
                    st.write("Portfolio drift checks:")
                    for note in proposal.drift_metrics:
                        st.write("-", note)
                if missing_gains_report:
                    st.write(
                        "Gains & Losses report missing—tax estimates assume $0 realized gains so far."
                    )

            withdrawal_csv = format_withdrawal_order_csv(proposal)
            st.download_button(
                label="Download withdrawal order checklist",
                data=withdrawal_csv,
                file_name=f"withdrawal_orders_{datetime.utcnow().date()}.csv",
                mime="text/csv",
            )

with strategy_tab:
    st.subheader("Direct Indexing Strategy Builder")

    strategy_upload = st.file_uploader(
        "Load strategy JSON", type="json", key="strategy_json_upload"
    )
    loaded_strategy: StrategySpec | None = None
    if strategy_upload:
        try:
            json_text = strategy_upload.read().decode("utf-8")
            loaded_strategy = StrategySpec.model_validate_json(json_text)
            st.success("Strategy JSON loaded")
        except Exception as exc:
            st.error(f"Unable to parse strategy JSON: {exc}")

    index_options = {
        "S&P 500": "sp500",
        "Total US": "total_us",
        "Nasdaq 100": "nasdaq100",
    }
    index_labels = list(index_options.keys())
    default_index_name = loaded_strategy.index_name if loaded_strategy else "sp500"
    default_index_label = next(
        (label for label, name in index_options.items() if name == default_index_name),
        "S&P 500",
    )
    index_choice = st.selectbox(
        "Index universe",
        options=index_labels,
        index=index_labels.index(default_index_label),
    )
    index_name = index_options[index_choice]

    holdings_default = loaded_strategy.holdings_count if loaded_strategy else 100
    holdings_count = st.slider(
        "Target holdings count",
        min_value=25,
        max_value=300,
        value=holdings_default,
        step=5,
    )

    max_weight_default = (
        (loaded_strategy.max_single_name_weight * 100)
        if loaded_strategy
        else 5.0
    )
    max_weight_pct = st.slider(
        "Max single-name weight (%)",
        min_value=0.5,
        max_value=10.0,
        value=max_weight_default,
        step=0.25,
    )

    screen_defaults = loaded_strategy.screens if loaded_strategy else {}
    screen_cols = st.columns(3)
    screen_values = {
        "oil_gas": screen_cols[0].checkbox(
            "Exclude Oil & Gas",
            value=screen_defaults.get("oil_gas", False),
        ),
        "tobacco": screen_cols[1].checkbox(
            "Exclude Tobacco",
            value=screen_defaults.get("tobacco", False),
        ),
        "weapons": screen_cols[2].checkbox(
            "Exclude Weapons",
            value=screen_defaults.get("weapons", False),
        ),
    }

    include_cash = st.checkbox(
        "Include cash equivalents",
        value=loaded_strategy.include_cash_equivalents if loaded_strategy else False,
    )

    holding_symbols = sorted({h.symbol for h in holdings})
    preset_exclusions = loaded_strategy.excluded_symbols if loaded_strategy else []
    exclusion_options = sorted(set(holding_symbols) | set(preset_exclusions))
    selected_exclusions = st.multiselect(
        "Exclude holdings",
        options=exclusion_options,
        default=preset_exclusions,
    )
    extra_exclusions_text = st.text_input(
        "Additional exclusions (comma-separated symbols)",
        value="",
    )
    extra_exclusions = [
        sym.strip().upper()
        for sym in extra_exclusions_text.split(",")
        if sym.strip()
    ]
    all_exclusions = sorted({*selected_exclusions, *extra_exclusions})

    strategy_spec = StrategySpec(
        index_name=index_name,
        holdings_count=holdings_count,
        max_single_name_weight=max_weight_pct / 100.0,
        screens=screen_values,
        excluded_symbols=all_exclusions,
        include_cash_equivalents=include_cash,
    )
    st.session_state["strategy_spec"] = strategy_spec.model_dump()

    try:
        universe_df = load_universe(strategy_spec.index_name)
    except Exception as exc:
        st.error(f"Unable to load universe: {exc}")
        universe_df = None

    if universe_df is not None:
        basket_df, strategy_warnings = build_target_basket(
            universe_df,
            strategy_spec,
            sector_map=sector_map or None,
        )

        if strategy_warnings:
            st.warning("; ".join(strategy_warnings))

        if basket_df.empty:
            st.info("No holdings remain after applying screens and exclusions.")
        else:
            top10 = basket_df.sort_values("weight", ascending=False).head(10)[
                "weight"
            ].sum()
            summary_cols = st.columns(3)
            summary_cols[0].metric(
                "Holdings in basket",
                f"{len(basket_df)}",
            )
            summary_cols[1].metric(
                "Top 10 weight",
                f"{top10:.2%}",
            )
            summary_cols[2].metric(
                "Max weight",
                f"{basket_df['weight'].max():.2%}",
            )

            display_df = basket_df.copy()
            display_df["weight_pct"] = display_df["weight"] * 100
            st.dataframe(
                display_df[["symbol", "weight", "weight_pct", "sector"]],
                hide_index=True,
            )

            basket_csv = export_basket_csv(basket_df)
            st.download_button(
                label="Download target basket CSV",
                data=basket_csv,
                file_name=f"target_basket_{strategy_spec.index_name}.csv",
                mime="text/csv",
            )
            st.session_state["strategy_basket"] = basket_df.to_dict("records")

    strategy_json = strategy_spec.model_dump_json(indent=2)
    st.download_button(
        label="Download strategy JSON",
        data=strategy_json,
        file_name="strategy_spec.json",
        mime="application/json",
    )

    loaded_basket = st.file_uploader(
        "Load saved target basket CSV",
        type="csv",
        key="uploaded_target_basket",
    )
    if loaded_basket:
        try:
            loaded_df = pd.read_csv(loaded_basket)
            st.write("Loaded target basket preview:")
            st.dataframe(loaded_df.head(20))
        except Exception as exc:
            st.error(f"Unable to parse target basket CSV: {exc}")

with transition_tab:
    st.subheader("Allocate & Transition")
    session_spec_data = st.session_state.get("strategy_spec")
    session_basket_records = st.session_state.get("strategy_basket")

    strategy_spec_input = None
    strategy_json_upload = st.file_uploader(
        "Upload strategy JSON", type="json", key="transition_strategy_json"
    )
    if strategy_json_upload:
        try:
            strategy_spec_input = StrategySpec.model_validate_json(
                strategy_json_upload.read().decode("utf-8")
            )
            st.success("Strategy JSON loaded for transition planning")
        except Exception as exc:
            st.error(f"Unable to parse strategy JSON: {exc}")
    elif session_spec_data:
        strategy_spec_input = StrategySpec(**session_spec_data)

    basket_upload = st.file_uploader(
        "Upload target basket CSV", type="csv", key="transition_basket_upload"
    )
    basket_df = None
    if basket_upload is not None:
        try:
            basket_df = pd.read_csv(basket_upload)
            st.success("Target basket CSV loaded")
        except Exception as exc:
            st.error(f"Unable to parse target basket CSV: {exc}")
    elif session_basket_records:
        basket_df = pd.DataFrame(session_basket_records)

    if strategy_spec_input is None or basket_df is None or basket_df.empty:
        st.info(
            "Load a strategy (JSON) and target basket CSV from the Strategy Builder tab to create a transition plan."
        )
    else:
        allocation_amount = st.number_input(
            "Allocation amount ($)", min_value=0.0, value=0.0, step=100.0
        )
        buffer_pct = (
            st.number_input("Buffer %", min_value=0.0, value=1.0, step=0.5) / 100.0
        )
        buffer_override = st.number_input(
            "Buffer override ($)", min_value=0.0, value=0.0, step=100.0
        )
        use_cash_first = st.checkbox("Use cash equivalents first", value=True)
        manual_cash = st.number_input(
            "Additional cash available ($)", min_value=0.0, value=0.0, step=100.0
        )

        holding_symbols = sorted({h.symbol for h in holdings})
        cash_symbols = [h.symbol for h in holdings if getattr(h, "is_cash_equivalent", False)]
        default_exclusions = sorted(set(cash_symbols))
        excluded = st.multiselect(
            "Exclude holdings from selling",
            options=holding_symbols,
            default=default_exclusions,
        )

        goal_labels_transition = {
            "Minimize taxes": "min_tax",
            "Balanced": "balanced",
            "Minimize drift": "min_drift",
        }
        goal_choice = st.selectbox(
            "Liquidation goal",
            options=list(goal_labels_transition.keys()),
        )

        tax_cols = st.columns(3)
        st_rate = tax_cols[0].number_input(
            "Short-term marginal rate (%)",
            min_value=0.0,
            max_value=70.0,
            value=32.0,
        )
        lt_rate = tax_cols[1].number_input(
            "Long-term capital gains rate (%)",
            min_value=0.0,
            max_value=50.0,
            value=15.0,
        )
        state_rate = tax_cols[2].number_input(
            "State tax rate (%)",
            min_value=0.0,
            max_value=20.0,
            value=5.0,
        )

        if allocation_amount <= 0:
            st.info("Enter an allocation amount to build a transition plan.")
        else:
            request = StrategyAllocationRequest(
                allocation_amount=allocation_amount,
                cash_buffer_amount=buffer_override if buffer_override > 0 else None,
                cash_buffer_pct=None if buffer_override > 0 else buffer_pct,
                manual_cash_available=manual_cash,
                use_cash_equivalents_first=use_cash_first,
                excluded_from_selling=excluded,
                liquidation_goal=goal_labels_transition[goal_choice],
                tax_rates=TaxRateInput(
                    short_term=st_rate / 100.0,
                    long_term=lt_rate / 100.0,
                    state=state_rate / 100.0,
                ),
            )

            try:
                plan = build_transition_plan(
                    holdings,
                    lots,
                    basket_df,
                    strategy_spec_input,
                    request,
                    realized_summary,
                )
            except Exception as exc:
                st.error(f"Unable to build transition plan: {exc}")
            else:
                summary_cols = st.columns(3)
                summary_cols[0].metric(
                    "Cash available",
                    format_currency(plan.cash_available),
                )
                summary_cols[1].metric(
                    "Cash needed from sells",
                    format_currency(plan.cash_needed_from_sales),
                )
                summary_cols[2].metric(
                    "Estimated total tax",
                    format_currency(plan.estimated_tax.total_tax),
                )
                st.metric(
                    "Estimated ST / LT realized",
                    f"{format_currency(plan.estimated_tax.st_realized)} / {format_currency(plan.estimated_tax.lt_realized)}",
                )

                if plan.warnings:
                    st.warning("Transition warnings:")
                    for warn in plan.warnings:
                        st.write("-", warn)

                if plan.sells:
                    sell_df = pd.DataFrame(
                        [
                            {
                                "symbol": sell.symbol,
                                "lot_id": sell.lot_id,
                                "acquired_date": sell.acquired_date,
                                "qty": sell.qty,
                                "price": sell.price,
                                "proceeds": sell.proceeds,
                                "basis": sell.basis,
                                "gain_loss": sell.gain_loss,
                                "term": sell.term.value,
                                "estimated_tax": sell.estimated_tax,
                                "rationale": "; ".join(sell.rationale),
                            }
                            for sell in plan.sells
                        ]
                    )
                    st.subheader("Sell plan")
                    st.dataframe(sell_df, hide_index=True)
                else:
                    st.info("No sells required; existing cash covers allocation.")

                if plan.buys:
                    buy_df = pd.DataFrame(
                        [
                            {
                                "symbol": buy.symbol,
                                "target_weight": buy.target_weight,
                                "target_dollars": buy.target_dollars,
                                "price": buy.price,
                                "est_shares": buy.est_shares,
                            }
                            for buy in plan.buys
                        ]
                    )
                    st.subheader("Buy targets")
                    st.dataframe(buy_df, hide_index=True)

                with st.expander("Why this plan?"):
                    st.write(plan.rationale_summary)
                    if plan.drift_metrics:
                        st.write("Drift notes:")
                        for note in plan.drift_metrics:
                            st.write("-", note)
                    if missing_gains_report:
                        st.write(
                            "Gains & Losses report missing — assumptions made for realized gains."
                        )

                sell_csv = format_sells_csv(plan.sells)
                buy_csv = format_buy_targets_csv(plan.buys)
                summary_txt = format_transition_summary(plan)
                st.download_button(
                    label="Download sell checklist (transition)",
                    data=sell_csv,
                    file_name="sell_checklist_transition.csv",
                    mime="text/csv",
                )
                st.download_button(
                    label="Download buy targets CSV",
                    data=buy_csv,
                    file_name="buy_targets_transition.csv",
                    mime="text/csv",
                )
                st.download_button(
                    label="Download transition summary",
                    data=summary_txt,
                    file_name="transition_summary.txt",
                    mime="text/plain",
                )
