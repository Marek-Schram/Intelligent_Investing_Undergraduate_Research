"""Macro and Fama-French factor data ingestion. TICKET-005.

Data source: FRED API (macro), Ken French Data Library (factors).
available_at logic: FRED series are available on publication date.
    Fama-French monthly data is available at end of month + ~5 days.
Spec section: docs/02 §6.

Gotcha: Ken French returns are PERCENT not decimal. Monthly table only. YYYYMM dates.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import TYPE_CHECKING

import pandas as pd
from fredapi import Fred

if TYPE_CHECKING:
    import duckdb

from durable.data.store import write_snapshot

logger = logging.getLogger(__name__)

FRED_SERIES = {
    "DGS10": "10-Year Treasury Constant Maturity Rate",
    "DGS2": "2-Year Treasury Constant Maturity Rate",
    "FEDFUNDS": "Federal Funds Effective Rate",
    "CPIAUCSL": "Consumer Price Index",
    "UNRATE": "Unemployment Rate",
    "VIXCLS": "CBOE Volatility Index",
    "BAMLH0A0HYM2": "US High Yield OAS",
    "T10Y2Y": "10Y-2Y Treasury Spread",
}


def fetch_fred_series(
    api_key: str,
    series_id: str,
    start: date | None = None,
) -> pd.DataFrame:
    """Fetch a single FRED series and format for the store.

    Returns DataFrame with: series_id, dt, value, available_at
    """
    fred = Fred(api_key=api_key)
    data = fred.get_series(series_id, observation_start=start)

    if data.empty:
        raise ValueError(f"No data returned for FRED series {series_id}")

    df = pd.DataFrame({"dt": data.index.date, "value": data.values})
    df["series_id"] = series_id
    df["available_at"] = pd.to_datetime(df["dt"]) + pd.Timedelta(days=1)
    df = df[["series_id", "dt", "value", "available_at"]]
    df = df.dropna(subset=["value"])

    return df


def fetch_all_fred(
    api_key: str,
    series_ids: list[str] | None = None,
    start: date | None = None,
) -> pd.DataFrame:
    """Fetch multiple FRED series."""
    if series_ids is None:
        series_ids = list(FRED_SERIES.keys())

    frames = []
    for sid in series_ids:
        try:
            df = fetch_fred_series(api_key, sid, start)
            frames.append(df)
            logger.info(f"Fetched {sid}: {len(df)} observations")
        except Exception as e:
            logger.warning(f"Failed to fetch {sid}: {e}")

    if not frames:
        raise ValueError("No FRED series could be fetched")

    return pd.concat(frames, ignore_index=True)


def fetch_fama_french(
    dataset: str = "F-F_Research_Data_5_Factors_2x3",
) -> pd.DataFrame:
    """Fetch Fama-French factor data from Ken French Data Library.

    Returns monthly factor returns as DECIMAL (converted from percent).
    Columns: series_id, dt, value, available_at
    """
    from pandas_datareader.famafrench import FamaFrenchReader

    reader = FamaFrenchReader(dataset, start="1960-01-01")
    tables = reader.read()
    reader.close()

    # tables[0] is the monthly data
    monthly = tables[0]

    # Convert from percent to decimal
    monthly = monthly / 100.0

    rows = []
    for dt_idx, row in monthly.iterrows():
        # dt_idx is a Period object like Period('2024-01', 'M')
        period_date = dt_idx.to_timestamp().date()
        # Last day of the month
        if period_date.month == 12:
            end_of_month = date(period_date.year, 12, 31)
        else:
            end_of_month = date(period_date.year, period_date.month + 1, 1)
            end_of_month = end_of_month.replace(day=1) - pd.Timedelta(days=1)
            end_of_month = end_of_month.date() if hasattr(end_of_month, "date") else end_of_month

        # FF data available ~5 days after month end
        available_at = datetime(end_of_month.year, end_of_month.month, end_of_month.day) + pd.Timedelta(days=5)

        for col in row.index:
            factor_name = f"FF5_{col.replace(' ', '_').replace('-', '_')}"
            rows.append({
                "series_id": factor_name,
                "dt": end_of_month,
                "value": float(row[col]),
                "available_at": available_at,
            })

    return pd.DataFrame(rows)


def fetch_momentum_factor() -> pd.DataFrame:
    """Fetch Fama-French momentum factor (MOM/UMD)."""
    from pandas_datareader.famafrench import FamaFrenchReader

    reader = FamaFrenchReader("F-F_Momentum_Factor", start="1960-01-01")
    tables = reader.read()
    reader.close()

    monthly = tables[0] / 100.0

    rows = []
    for dt_idx, row in monthly.iterrows():
        period_date = dt_idx.to_timestamp().date()
        if period_date.month == 12:
            end_of_month = date(period_date.year, 12, 31)
        else:
            end_of_month = date(period_date.year, period_date.month + 1, 1)
            end_of_month = end_of_month.replace(day=1) - pd.Timedelta(days=1)
            end_of_month = end_of_month.date() if hasattr(end_of_month, "date") else end_of_month

        available_at = datetime(end_of_month.year, end_of_month.month, end_of_month.day) + pd.Timedelta(days=5)

        for col in row.index:
            rows.append({
                "series_id": f"FF_MOM_{col.replace(' ', '_')}",
                "dt": end_of_month,
                "value": float(row[col]),
                "available_at": available_at,
            })

    return pd.DataFrame(rows)


def ingest_macro(
    conn: "duckdb.DuckDBPyConnection",
    api_key: str,
    series_ids: list[str] | None = None,
    snapshot_id: str | None = None,
) -> str:
    """Fetch and store FRED macro series."""
    df = fetch_all_fred(api_key, series_ids)

    if snapshot_id is None:
        snapshot_id = f"macro-fred-{date.today().isoformat()}"

    write_snapshot(conn, "macro_series", df, snapshot_id)
    logger.info(f"Ingested {len(df)} macro observations as {snapshot_id}")
    return snapshot_id


def ingest_factors(
    conn: "duckdb.DuckDBPyConnection",
    snapshot_id: str | None = None,
) -> str:
    """Fetch and store Fama-French factors."""
    ff5 = fetch_fama_french()
    mom = fetch_momentum_factor()
    df = pd.concat([ff5, mom], ignore_index=True)

    if snapshot_id is None:
        snapshot_id = f"factors-ff5mom-{date.today().isoformat()}"

    write_snapshot(conn, "macro_series", df, snapshot_id)
    logger.info(f"Ingested {len(df)} factor observations as {snapshot_id}")
    return snapshot_id


def get_risk_free_rate(
    conn: "duckdb.DuckDBPyConnection",
    as_of_date: date,
) -> float | None:
    """Get the most recent 10Y Treasury rate as of a date."""
    from durable.data.store import as_of

    df = as_of(conn, "macro_series", as_of_date)
    dgs10 = df[df["series_id"] == "DGS10"].sort_values("dt")

    if dgs10.empty:
        return None

    return float(dgs10.iloc[-1]["value"]) / 100.0
