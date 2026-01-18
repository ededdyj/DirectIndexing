"""Download and normalize index universes from public ETF sources."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Dict

import pandas as pd
import requests


ROOT = Path(__file__).resolve().parents[1]
UNIVERSE_DIR = ROOT / "data" / "universes"
USER_AGENT = {"User-Agent": "DirectIndexingBot/0.1 (+for compliance review)"}


ICB_TO_GICS: Dict[str, str] = {
    "Technology": "Information Technology",
    "Telecommunications": "Communication Services",
    "Basic Materials": "Materials",
    "Consumer Discretionary": "Consumer Discretionary",
    "Consumer Staples": "Consumer Staples",
    "Energy": "Energy",
    "Health Care": "Health Care",
    "Industrials": "Industrials",
    "Real Estate": "Real Estate",
    "Utilities": "Utilities",
}

MANUAL_SECTOR_OVERRIDES = {
    # Nasdaq-100 additions sometimes lag Wikipedia updates; apply known mapping.
    "GFS": "Information Technology",  # GlobalFoundries – semiconductor foundry
}


def read_ishares_holdings(url: str) -> pd.DataFrame:
    resp = requests.get(url, headers=USER_AGENT, timeout=60)
    resp.raise_for_status()
    text = resp.content.decode("utf-8-sig")
    lines = text.splitlines()
    header_idx = next(
        (i for i, line in enumerate(lines) if line.startswith("Ticker")), None
    )
    if header_idx is None:
        raise ValueError(f"Unable to find header row in iShares file: {url}")
    csv_text = "\n".join(lines[header_idx:])
    df = pd.read_csv(io.StringIO(csv_text))
    required_cols = {"Ticker", "Sector", "Weight (%)"}
    if not required_cols.issubset(df.columns):
        raise ValueError(f"Missing required columns in iShares file: {url}")
    df = df[df["Asset Class"].str.contains("Equity", na=False)].copy()
    df = df[["Ticker", "Sector", "Weight (%)"]]
    df["symbol"] = df["Ticker"].astype(str).str.upper().str.strip()
    df["sector"] = df["Sector"].astype(str).str.strip()
    df["weight"] = (
        pd.to_numeric(df["Weight (%)"].astype(str).str.replace("%", ""), errors="coerce")
        / 100.0
    )
    df = df.dropna(subset=["weight"]).copy()
    df = df.groupby("symbol", as_index=False).agg({"weight": "sum", "sector": "first"})
    df["weight"] = df["weight"] / df["weight"].sum()
    return df[["symbol", "weight", "sector"]]


def fetch_sp500() -> pd.DataFrame:
    """Use iShares Core S&P 500 ETF (IVV) holdings as SPY proxy weights."""
    url = (
        "https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf/"
        "1467271812596.ajax?fileType=csv&fileName=IVV_holdings&dataType=fund"
    )
    df = read_ishares_holdings(url)
    _validate_weights(df, "S&P 500")
    return df


def fetch_total_us() -> pd.DataFrame:
    """Use iShares Core S&P Total US Stock Market ETF (ITOT) holdings."""
    url = (
        "https://www.ishares.com/us/products/239724/ishares-core-sp-total-us-stock-market-etf/"
        "1467271812596.ajax?fileType=csv&fileName=ITOT_holdings&dataType=fund"
    )
    df = read_ishares_holdings(url)
    _validate_weights(df, "Total US")
    return df


def fetch_nasdaq100(sector_lookup: Dict[str, str]) -> pd.DataFrame:
    """Use Slickcharts weights (QQQ proxy) and sector data from Wikipedia/ITOT."""
    slick_html = requests.get(
        "https://www.slickcharts.com/nasdaq100", headers=USER_AGENT, timeout=60
    ).text
    weight_df = pd.read_html(slick_html)[0]
    weight_df["symbol"] = weight_df["Symbol"].astype(str).str.upper().str.strip()
    weight_df["weight"] = (
        pd.to_numeric(weight_df["Weight"].str.replace("%", "")) / 100.0
    )
    wiki_html = requests.get(
        "https://en.wikipedia.org/wiki/Nasdaq-100", headers=USER_AGENT, timeout=60
    ).text
    sector_table = pd.read_html(wiki_html)[4]
    sector_table["symbol"] = (
        sector_table["Ticker"].astype(str).str.upper().str.strip()
    )
    sector_table["sector"] = sector_table["ICB Industry[14]"].map(ICB_TO_GICS)
    icb_sector_map = dict(zip(sector_table["symbol"], sector_table["sector"]))

    df = weight_df.copy()
    df["sector"] = df["symbol"].map(sector_lookup)
    missing_mask = df["sector"].isna()
    if missing_mask.any():
        df.loc[missing_mask, "sector"] = df.loc[missing_mask, "symbol"].map(
            icb_sector_map
        )
    still_missing = df["sector"].isna()
    if still_missing.any():
        df.loc[still_missing, "sector"] = df.loc[still_missing, "symbol"].map(
            MANUAL_SECTOR_OVERRIDES
        )
    if df["sector"].isna().any():
        missing = df[df["sector"].isna()]["symbol"].tolist()
        raise ValueError(f"Missing sector for symbols: {missing}")
    df = df[["symbol", "weight", "sector"]]
    df["weight"] = df["weight"] / df["weight"].sum()
    _validate_weights(df, "Nasdaq-100")
    return df


def _validate_weights(df: pd.DataFrame, name: str) -> None:
    if df["weight"].isnull().any():
        raise ValueError(f"{name}: weight column contains NaN")
    total = df["weight"].sum()
    if not 0.99 <= total <= 1.01:
        raise ValueError(f"{name}: weights sum to {total:.4f}, expected ≈ 1.0")
    dupes = df[df["symbol"].duplicated()]["symbol"].tolist()
    if dupes:
        raise ValueError(f"{name}: duplicate symbols detected: {dupes}")


def save_universe(name: str, df: pd.DataFrame) -> None:
    path = UNIVERSE_DIR / f"{name}_universe.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.sort_values("symbol").to_csv(path, index=False)
    print(f"Updated {path} ({len(df)} constituents)")


def main() -> None:
    total_df = fetch_total_us()
    save_universe("total_us", total_df)
    sector_lookup = dict(zip(total_df["symbol"], total_df["sector"]))
    save_universe("sp500", fetch_sp500())
    save_universe("nasdaq100", fetch_nasdaq100(sector_lookup))


if __name__ == "__main__":
    main()
