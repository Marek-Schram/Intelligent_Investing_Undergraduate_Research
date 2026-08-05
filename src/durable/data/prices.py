"""Price data ingestion — raw OHLCV only. TICKET-003.

Data source: Alpaca Markets IEX (free, paper key), raw OHLCV.
available_at logic: bars are available at market close on the trade date,
    so available_at = trade_date (end of day).
Spec section: docs/02 §4, SPEC §2.

CRITICAL: Never use adjusted-close-only series. The firewall rejects them.
Adjusted prices are retroactively restated on every split/dividend, so today's
series differs from what existed at the historical date.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

if TYPE_CHECKING:
    import duckdb

from durable.data.store import write_snapshot

logger = logging.getLogger(__name__)


class AdjustedPriceError(Exception):
    """Raised when adjusted-only prices are detected."""


def get_price_client(api_key: str, secret_key: str) -> StockHistoricalDataClient:
    return StockHistoricalDataClient(api_key, secret_key)


def fetch_daily_bars(
    client: StockHistoricalDataClient,
    ticker: str,
    start: date,
    end: date | None = None,
) -> pd.DataFrame:
    """Fetch raw daily OHLCV bars from Alpaca.

    Returns DataFrame with columns: ticker, dt, open, high, low, close, volume, available_at
    """
    if end is None:
        end = date.today() - timedelta(days=1)

    req = StockBarsRequest(
        symbol_or_symbols=ticker,
        timeframe=TimeFrame.Day,
        start=datetime(start.year, start.month, start.day),
        end=datetime(end.year, end.month, end.day),
    )
    bars = client.get_stock_bars(req)
    df = bars.df

    if df.empty:
        raise ValueError(f"No price data returned for {ticker} from {start} to {end}")

    df = df.reset_index()
    df = df.rename(columns={"symbol": "ticker", "timestamp": "dt"})

    df["dt"] = pd.to_datetime(df["dt"]).dt.date
    df["available_at"] = pd.to_datetime(df["dt"]) + pd.Timedelta(hours=16)

    df = df[["ticker", "dt", "open", "high", "low", "close", "volume", "available_at"]]

    _assert_raw_ohlcv(df)

    return df


def _assert_raw_ohlcv(df: pd.DataFrame) -> None:
    """Verify this is raw OHLCV data, not adjusted-only."""
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise AdjustedPriceError(
            f"Missing raw OHLCV columns: {missing}. "
            "Adjusted-close-only series are rejected — they retroactively leak corporate actions."
        )
    if df["volume"].isna().all():
        raise AdjustedPriceError("All volume values are NaN — likely adjusted-only data")


def assert_not_adjusted_only(df: pd.DataFrame) -> None:
    """Public assertion for use by the firewall. Raises AdjustedPriceError."""
    _assert_raw_ohlcv(df)


def add_known_corporate_action(
    conn: "duckdb.DuckDBPyConnection",
    ticker: str,
    ex_date: date,
    action_type: str,
    factor: float,
    description: str,
    snapshot_id: str,
) -> None:
    """Manually add a known corporate action (for cases where auto-detection fails)."""
    available_at = datetime(ex_date.year, ex_date.month, ex_date.day)
    df = pd.DataFrame(
        [
            {
                "ticker": ticker,
                "ex_date": ex_date,
                "action_type": action_type,
                "factor": factor,
                "description": description,
                "available_at": available_at,
            }
        ]
    )
    write_snapshot(conn, "corporate_actions", df, snapshot_id)


def ingest_daily_bars(
    conn: "duckdb.DuckDBPyConnection",
    client: StockHistoricalDataClient,
    ticker: str,
    start: date,
    end: date | None = None,
    snapshot_id: str | None = None,
) -> str:
    """Fetch and store daily bars for a ticker."""
    df = fetch_daily_bars(client, ticker, start, end)

    if snapshot_id is None:
        snapshot_id = f"bars-{ticker.lower()}-{date.today().isoformat()}"

    write_snapshot(conn, "bars_daily", df, snapshot_id)
    logger.info(f"Ingested {len(df)} bars for {ticker} as {snapshot_id}")
    return snapshot_id


def get_total_return(
    conn: "duckdb.DuckDBPyConnection",
    ticker: str,
    start_date: date,
    end_date: date,
    as_of_date: date | None = None,
) -> float:
    """Calculate total return from raw prices, adjusting for splits.

    Uses close-to-close return adjusted by corporate action factors.
    """
    from durable.data.store import as_of

    if as_of_date is None:
        as_of_date = end_date

    bars = as_of(conn, "bars_daily", as_of_date, tickers=ticker)
    bars = bars[(bars["dt"] >= start_date) & (bars["dt"] <= end_date)]
    bars = bars.sort_values("dt")

    if len(bars) < 2:
        return 0.0

    actions = as_of(conn, "corporate_actions", as_of_date, tickers=ticker)
    splits = actions[
        (actions["action_type"] == "split")
        & (actions["ex_date"] >= start_date)
        & (actions["ex_date"] <= end_date)
    ]

    cumulative_factor = splits["factor"].prod() if not splits.empty else 1.0

    start_price = bars.iloc[0]["close"]
    end_price = bars.iloc[-1]["close"]

    adjusted_start = start_price / cumulative_factor
    return (end_price - adjusted_start) / adjusted_start
