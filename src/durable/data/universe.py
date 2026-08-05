"""Point-in-time universe construction. TICKET-004.

Data source: SEC EDGAR (company metadata) + bars_daily (for cap/ADV/price).
available_at logic: universe membership is determined from data available at the
    rebalance date. Delisted companies MUST appear in historical universes.
Spec section: SPEC §1 Universe.

Key invariant: 2008 universe contains LEH/WM/BSC. Dead companies stay in.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    import duckdb

from durable.data.store import as_of

logger = logging.getLogger(__name__)

EXCHANGES = {"NYSE", "NASDAQ", "AMEX"}

EXCLUDED_SIC_BIOTECH = {"2836", "8731"}
FINANCIAL_SIC_RANGE = range(6000, 6500)

UNIVERSE_PARAMS_DEFAULT = {
    "min_market_cap": 2_000_000_000,
    "min_adv_60d": 10_000_000,
    "min_price": 5.0,
    "min_quarters_filed": 8,
    "min_months_since_ipo": 24,
    "min_revenue_biotech": 50_000_000,
}


class ExclusionReason:
    """Tracks why a ticker was excluded, for audit trail."""

    def __init__(self, ticker: str, reason: str):
        self.ticker = ticker
        self.reason = reason

    def __repr__(self) -> str:
        return f"Excluded({self.ticker!r}: {self.reason})"


def build_universe(
    conn: "duckdb.DuckDBPyConnection",
    as_of_date: date,
    params: dict | None = None,
) -> tuple[pd.DataFrame, list[ExclusionReason]]:
    """Build the investable universe as of a given date.

    Returns:
        - DataFrame of eligible tickers with metadata (ticker, market_cap, adv_60d, etc.)
        - List of exclusions with reasons (for audit)

    Delisted companies appear in universes dated before their delisting.
    """
    if params is None:
        params = UNIVERSE_PARAMS_DEFAULT.copy()

    exclusions: list[ExclusionReason] = []

    # Get all tickers that have fundamentals available as of this date
    fundamentals = as_of(conn, "facts_fundamentals", as_of_date)
    if fundamentals.empty:
        return pd.DataFrame(columns=["ticker", "market_cap", "adv_60d", "price", "sic"]), exclusions

    tickers_with_data = fundamentals["ticker"].unique().tolist()

    # Get price data for these tickers
    bars = as_of(conn, "bars_daily", as_of_date)

    # Build ticker-level summary
    universe_rows: list[dict] = []
    for ticker in tickers_with_data:
        ticker_bars = bars[bars["ticker"] == ticker]
        ticker_fundamentals = fundamentals[fundamentals["ticker"] == ticker]

        # Price and volume from recent bars
        recent_bars = ticker_bars.sort_values("dt").tail(60)
        if recent_bars.empty:
            exclusions.append(ExclusionReason(ticker, "no_price_data"))
            continue

        latest_price = recent_bars.iloc[-1]["close"]
        adv_60d = (recent_bars["close"] * recent_bars["volume"]).median()

        # Market cap from shares outstanding × price
        shares_data = ticker_fundamentals[
            ticker_fundamentals["field"] == "shares_outstanding"
        ]
        if shares_data.empty:
            exclusions.append(ExclusionReason(ticker, "no_shares_outstanding"))
            continue

        latest_shares = shares_data.sort_values("period_end").iloc[-1]["value"]
        market_cap = latest_shares * latest_price

        # Count quarters filed
        quarters_filed = ticker_fundamentals[
            ticker_fundamentals["field"] == "revenue"
        ]["period_end"].nunique()

        # Get SIC code if available (would come from company metadata)
        sic = _get_sic_code(ticker_fundamentals)

        universe_rows.append(
            {
                "ticker": ticker,
                "market_cap": market_cap,
                "adv_60d": adv_60d,
                "price": latest_price,
                "quarters_filed": quarters_filed,
                "sic": sic,
                "shares_outstanding": latest_shares,
            }
        )

    if not universe_rows:
        return pd.DataFrame(columns=["ticker", "market_cap", "adv_60d", "price", "sic"]), exclusions

    df = pd.DataFrame(universe_rows)

    # Apply filters
    df, new_exclusions = _apply_filters(df, params)
    exclusions.extend(new_exclusions)

    return df, exclusions


def _apply_filters(
    df: pd.DataFrame, params: dict
) -> tuple[pd.DataFrame, list[ExclusionReason]]:
    """Apply universe filters. Every exclusion gets a reason."""
    exclusions: list[ExclusionReason] = []
    mask = pd.Series(True, index=df.index)

    # Market cap filter
    cap_fail = df["market_cap"] < params["min_market_cap"]
    for ticker in df.loc[cap_fail, "ticker"]:
        exclusions.append(ExclusionReason(ticker, f"market_cap_below_{params['min_market_cap']}"))
    mask &= ~cap_fail

    # ADV filter
    adv_fail = df["adv_60d"] < params["min_adv_60d"]
    for ticker in df.loc[adv_fail, "ticker"]:
        exclusions.append(ExclusionReason(ticker, f"adv_below_{params['min_adv_60d']}"))
    mask &= ~adv_fail

    # Price filter
    price_fail = df["price"] < params["min_price"]
    for ticker in df.loc[price_fail, "ticker"]:
        exclusions.append(ExclusionReason(ticker, "price_below_5"))
    mask &= ~price_fail

    # Quarters filed
    quarters_fail = df["quarters_filed"] < params["min_quarters_filed"]
    for ticker in df.loc[quarters_fail, "ticker"]:
        exclusions.append(ExclusionReason(ticker, "insufficient_quarters_filed"))
    mask &= ~quarters_fail

    # Pre-revenue biotech exclusion
    if "sic" in df.columns:
        biotech_mask = df["sic"].isin(EXCLUDED_SIC_BIOTECH)
        # Would need revenue data here — for now flag based on SIC alone
        for ticker in df.loc[biotech_mask, "ticker"]:
            exclusions.append(ExclusionReason(ticker, "pre_revenue_biotech_sic"))
        # Only exclude if we can confirm pre-revenue (< $50M)
        # This requires additional revenue check in practice

    result = df[mask].reset_index(drop=True)
    return result, exclusions


def _get_sic_code(ticker_fundamentals: pd.DataFrame) -> str | None:
    """Extract SIC code from fundamentals (if available as a stored field)."""
    # SIC would be stored as a metadata field during ingestion
    # For now return None — will be populated from EDGAR company metadata
    return None


def is_financial(sic: str | None) -> bool:
    """Check if a company is a financial (SIC 6000-6499) for variant scoring."""
    if sic is None:
        return False
    try:
        return int(sic) in FINANCIAL_SIC_RANGE
    except (ValueError, TypeError):
        return False


def universe_contains_delisted(
    conn: "duckdb.DuckDBPyConnection",
    as_of_date: date,
    expected_tickers: list[str],
) -> dict[str, bool]:
    """Verify that specific (possibly delisted) tickers appear in a historical universe.

    Returns dict of ticker -> present_in_universe. Used for the invariant test:
    2008 universe must contain LEH, WM, BSC.
    """
    universe_df, _ = build_universe(conn, as_of_date)
    universe_tickers = set(universe_df["ticker"].tolist()) if not universe_df.empty else set()
    return {t: t in universe_tickers for t in expected_tickers}
