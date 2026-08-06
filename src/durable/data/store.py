"""Point-in-time DuckDB store. TICKET-001.

Data source: all ingested data (SEC, prices, macro, insider, 13F, etc.)
available_at logic: every table row has an `available_at` timestamp; `as_of(T)` filters
    to rows where `available_at <= T`, making look-ahead structurally impossible.
Spec section: docs/01 Architecture, docs/02 Data Sources.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
import pandas as pd

if TYPE_CHECKING:
    from collections.abc import Sequence

_TABLES: dict[str, str] = {
    "facts_fundamentals": """
        CREATE TABLE IF NOT EXISTS facts_fundamentals (
            ticker VARCHAR NOT NULL,
            field VARCHAR NOT NULL,
            period_end DATE NOT NULL,
            value DOUBLE,
            filed_at TIMESTAMP NOT NULL,
            available_at TIMESTAMP NOT NULL,
            accession VARCHAR,
            restated BOOLEAN DEFAULT FALSE,
            snapshot_id VARCHAR NOT NULL
        )
    """,
    "bars_daily": """
        CREATE TABLE IF NOT EXISTS bars_daily (
            ticker VARCHAR NOT NULL,
            dt DATE NOT NULL,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume BIGINT,
            available_at TIMESTAMP NOT NULL,
            snapshot_id VARCHAR NOT NULL
        )
    """,
    "corporate_actions": """
        CREATE TABLE IF NOT EXISTS corporate_actions (
            ticker VARCHAR NOT NULL,
            ex_date DATE NOT NULL,
            action_type VARCHAR NOT NULL,
            factor DOUBLE,
            description VARCHAR,
            available_at TIMESTAMP NOT NULL,
            snapshot_id VARCHAR NOT NULL
        )
    """,
    "macro_series": """
        CREATE TABLE IF NOT EXISTS macro_series (
            series_id VARCHAR NOT NULL,
            dt DATE NOT NULL,
            value DOUBLE,
            available_at TIMESTAMP NOT NULL,
            snapshot_id VARCHAR NOT NULL
        )
    """,
    "insider_txns": """
        CREATE TABLE IF NOT EXISTS insider_txns (
            ticker VARCHAR NOT NULL,
            filer_name VARCHAR,
            filer_title VARCHAR,
            txn_date DATE,
            txn_code VARCHAR NOT NULL,
            shares DOUBLE,
            price DOUBLE,
            shares_after DOUBLE,
            is_10b5_1 BOOLEAN,
            filed_at TIMESTAMP NOT NULL,
            available_at TIMESTAMP NOT NULL,
            accession VARCHAR,
            snapshot_id VARCHAR NOT NULL
        )
    """,
    "political_txns": """
        CREATE TABLE IF NOT EXISTS political_txns (
            ticker VARCHAR NOT NULL,
            member_name VARCHAR NOT NULL,
            chamber VARCHAR,
            txn_type VARCHAR NOT NULL,
            txn_date DATE,
            amount_low DOUBLE,
            amount_high DOUBLE,
            committees VARCHAR,
            filed_at TIMESTAMP NOT NULL,
            available_at TIMESTAMP NOT NULL,
            snapshot_id VARCHAR NOT NULL
        )
    """,
    "institutional_holdings": """
        CREATE TABLE IF NOT EXISTS institutional_holdings (
            manager_cik INT,
            manager_name VARCHAR,
            ticker VARCHAR NOT NULL,
            cusip VARCHAR,
            shares DOUBLE,
            value DOUBLE,
            period_end DATE,
            filed_at TIMESTAMP NOT NULL,
            available_at TIMESTAMP NOT NULL,
            pct_of_portfolio DOUBLE,
            change_type VARCHAR,
            snapshot_id VARCHAR NOT NULL
        )
    """,
    "short_interest": """
        CREATE TABLE IF NOT EXISTS short_interest (
            ticker VARCHAR NOT NULL,
            settlement_date DATE,
            publication_date DATE,
            available_at TIMESTAMP NOT NULL,
            shares_short BIGINT,
            pct_float DOUBLE,
            days_to_cover DOUBLE,
            snapshot_id VARCHAR NOT NULL
        )
    """,
    "credit_spreads": """
        CREATE TABLE IF NOT EXISTS credit_spreads (
            ticker VARCHAR NOT NULL,
            cusip VARCHAR,
            dt DATE NOT NULL,
            yield DOUBLE,
            benchmark_yield DOUBLE,
            spread_bps DOUBLE,
            available_at TIMESTAMP NOT NULL,
            snapshot_id VARCHAR NOT NULL
        )
    """,
    "filing_extractions": """
        CREATE TABLE IF NOT EXISTS filing_extractions (
            accession VARCHAR NOT NULL,
            ticker VARCHAR NOT NULL,
            field VARCHAR NOT NULL,
            value VARCHAR,
            citation VARCHAR,
            confidence DOUBLE,
            prompt_version VARCHAR NOT NULL,
            model_version VARCHAR NOT NULL,
            extracted_at TIMESTAMP,
            available_at TIMESTAMP NOT NULL,
            snapshot_id VARCHAR NOT NULL
        )
    """,
    "factor_ic": """
        CREATE TABLE IF NOT EXISTS factor_ic (
            as_of DATE NOT NULL,
            factor VARCHAR NOT NULL,
            horizon_q INT NOT NULL,
            ic DOUBLE,
            n_names INT,
            snapshot_id VARCHAR NOT NULL
        )
    """,
    "firewall_violations": """
        CREATE TABLE IF NOT EXISTS firewall_violations (
            detected_at TIMESTAMP NOT NULL,
            table_name VARCHAR NOT NULL,
            as_of DATE,
            n_rows INT,
            detail VARCHAR
        )
    """,
    "tax_lots": """
        CREATE TABLE IF NOT EXISTS tax_lots (
            lot_id VARCHAR PRIMARY KEY,
            ticker VARCHAR NOT NULL,
            sleeve VARCHAR NOT NULL,
            account VARCHAR NOT NULL,
            acquired_at DATE NOT NULL,
            shares DOUBLE NOT NULL,
            cost_basis_per_share DECIMAL(18,6) NOT NULL,
            adjusted_basis DECIMAL(18,6),
            wash_sale_deferred DECIMAL(18,6) DEFAULT 0,
            holding_start DATE NOT NULL,
            closed_at DATE,
            proceeds DECIMAL(18,6),
            realized_gain DECIMAL(18,6),
            term VARCHAR
        )
    """,
    "snapshots": """
        CREATE TABLE IF NOT EXISTS snapshots (
            snapshot_id VARCHAR PRIMARY KEY,
            table_name VARCHAR NOT NULL,
            created_at TIMESTAMP NOT NULL,
            row_count INT NOT NULL,
            description VARCHAR
        )
    """,
}

_INDEXES: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_facts_ticker_avail ON facts_fundamentals (ticker, available_at)",
    "CREATE INDEX IF NOT EXISTS idx_bars_ticker_avail ON bars_daily (ticker, available_at)",
    "CREATE INDEX IF NOT EXISTS idx_bars_ticker_dt ON bars_daily (ticker, dt)",
    "CREATE INDEX IF NOT EXISTS idx_actions_ticker ON corporate_actions (ticker, ex_date)",
    "CREATE INDEX IF NOT EXISTS idx_macro_series_avail ON macro_series (series_id, available_at)",
    "CREATE INDEX IF NOT EXISTS idx_insider_ticker_avail ON insider_txns (ticker, available_at)",
    "CREATE INDEX IF NOT EXISTS idx_political_ticker_avail ON political_txns (ticker, available_at)",
    "CREATE INDEX IF NOT EXISTS idx_inst_ticker_avail ON institutional_holdings (ticker, available_at)",
    "CREATE INDEX IF NOT EXISTS idx_short_ticker_avail ON short_interest (ticker, available_at)",
    "CREATE INDEX IF NOT EXISTS idx_credit_ticker_avail ON credit_spreads (ticker, available_at)",
    "CREATE INDEX IF NOT EXISTS idx_extract_ticker_avail ON filing_extractions (ticker, available_at)",
    "CREATE INDEX IF NOT EXISTS idx_ic_factor ON factor_ic (factor, as_of)",
]


class DuplicateSnapshotError(Exception):
    pass


class LeakageError(AssertionError):
    """Raised when as_of filtering finds rows that violate point-in-time constraints.

    Subclasses AssertionError deliberately — must never be caught and handled.
    """


def get_conn(path: str | Path | None = None) -> duckdb.DuckDBPyConnection:
    """Open or create a DuckDB database. In-memory if path is None or ':memory:'."""
    if path is None or str(path) == ":memory:":
        return duckdb.connect(":memory:")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path))


def init_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create all tables and indexes. Idempotent."""
    for ddl in _TABLES.values():
        conn.execute(ddl)
    for idx in _INDEXES:
        conn.execute(idx)


def write_snapshot(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    df: pd.DataFrame,
    snapshot_id: str,
    description: str | None = None,
) -> None:
    """Append rows to a table with a unique snapshot_id. Raises on duplicate."""
    if table not in _TABLES:
        raise ValueError(f"Unknown table: {table!r}. Valid: {sorted(_TABLES.keys())}")
    if table in ("snapshots", "firewall_violations", "tax_lots"):
        raise ValueError(f"Table {table!r} is not snapshot-appendable")

    existing = conn.execute(
        "SELECT 1 FROM snapshots WHERE snapshot_id = ?", [snapshot_id]
    ).fetchone()
    if existing is not None:
        raise DuplicateSnapshotError(
            f"Snapshot {snapshot_id!r} already exists. Snapshots are immutable."
        )

    if df.empty:
        raise ValueError("Cannot write an empty DataFrame as a snapshot")

    if "snapshot_id" in df.columns:
        raise ValueError(
            "DataFrame must not contain a 'snapshot_id' column; it is set by the store"
        )

    df_with_id = df.assign(snapshot_id=snapshot_id)

    conn.execute(f"INSERT INTO {table} SELECT * FROM df_with_id")

    conn.execute(
        "INSERT INTO snapshots (snapshot_id, table_name, created_at, row_count, description) "
        "VALUES (?, ?, ?, ?, ?)",
        [snapshot_id, table, datetime.now(UTC), len(df), description],
    )


def as_of(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    ts: date | datetime | str,
    tickers: str | Sequence[str] | None = None,
) -> pd.DataFrame:
    """Point-in-time query: returns only rows where available_at <= ts.

    This is THE look-ahead guard. Every read path goes through here.
    """
    if table not in _TABLES:
        raise ValueError(f"Unknown table: {table!r}")
    if table in ("snapshots", "firewall_violations", "tax_lots"):
        raise ValueError(f"Table {table!r} does not support as_of filtering")

    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    elif isinstance(ts, date) and not isinstance(ts, datetime):
        ts = datetime(ts.year, ts.month, ts.day, 23, 59, 59)

    query = f"SELECT * FROM {table} WHERE available_at <= ?"
    params: list = [ts]

    if tickers is not None:
        if isinstance(tickers, str):
            tickers = [tickers]
        tickers = list(tickers)
        query += " AND ticker IN (SELECT UNNEST(?))"
        params.append(tickers)

    result = conn.execute(query, params).fetch_arrow_table().to_pandas()

    _assert_no_future_fast(result, ts, table)

    return result


def _assert_no_future_fast(df: pd.DataFrame, ts: datetime, table: str) -> None:
    """Independent assertion that no rows leak future data. Belt-and-suspenders.

    Uses .max() instead of a full boolean mask for speed on large DataFrames.
    """
    if df.empty or "available_at" not in df.columns:
        return
    max_ts = df["available_at"].max()
    if max_ts > ts:
        future_mask = df["available_at"] > ts
        n = future_mask.sum()
        sample = df.loc[future_mask, "available_at"].iloc[:3].tolist()
        raise LeakageError(
            f"as_of({table}, {ts}): {n} rows have available_at in the future. "
            f"Sample timestamps: {sample}"
        )


def list_snapshots(conn: duckdb.DuckDBPyConnection, table: str | None = None) -> pd.DataFrame:
    """Return the snapshot registry, optionally filtered by table."""
    query = "SELECT * FROM snapshots"
    params: list = []
    if table is not None:
        query += " WHERE table_name = ?"
        params.append(table)
    query += " ORDER BY created_at"
    return conn.execute(query, params).fetchdf()


def row_count(conn: duckdb.DuckDBPyConnection, table: str) -> int:
    """Return the number of rows in a table."""
    if table not in _TABLES:
        raise ValueError(f"Unknown table: {table!r}")
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
