"""Leakage firewall. TICKET-042.

An INDEPENDENT assertion layer that every data-returning function must pass through.

Why this exists on top of `store.as_of()`: the store is the primary guard, but it only protects
paths that go through the store. A firewall wrapped around the boundary catches the paths that
do not -- a direct SQL query, a CSV read, a vendor SDK call, a helper someone added at 2am.

Adapted from the `agent-backtest-lab` pattern: a hard firewall that refuses any row whose
timestamp exceeds `as_of`, and a loader that refuses adjusted-close-only price series.

See docs/13 section 2.2.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    import duckdb

logger = logging.getLogger(__name__)

# Raw OHLCV columns that must be present in a price frame.
_RAW_OHLCV_COLS = {"open", "high", "low", "close", "volume"}

# Tables with available_at columns for the audit sweep.
_AUDITABLE_TABLES = [
    "facts_fundamentals",
    "bars_daily",
    "corporate_actions",
    "macro_series",
    "insider_txns",
    "political_txns",
    "institutional_holdings",
    "short_interest",
    "credit_spreads",
    "filing_extractions",
]

# Lagged-disclosure minimum lag expectations (calendar days).
_MIN_LAGS: dict[str, int] = {
    "13f": 45,
    "stock_act": 45,
    "short_interest": 11,
}


class LeakageError(AssertionError):
    """Raised when data newer than the as-of date reaches a caller.

    This is deliberately an AssertionError subclass: it should never be caught and
    handled. If it fires, a backtest result is invalid and must be discarded.
    """


class AdjustedPriceError(ValueError):
    """Raised when an adjusted-close-only price series is used.

    Adjusted prices are RETROACTIVELY RESTATED on every split and dividend. A series
    downloaded today does not equal the series that existed at the historical date, so
    using one silently leaks future corporate actions into the past.

    Load raw OHLCV plus an explicit corporate-action table instead.
    """


def assert_no_future(
    df: pd.DataFrame,
    as_of: pd.Timestamp,
    time_col: str = "available_at",
    source: str = "",
) -> pd.DataFrame:
    """Hard-fail if ANY row has `time_col` > `as_of`. Returns df unchanged if clean.

    Every public data function ends with `return assert_no_future(df, as_of, source=__name__)`.

    Raises LeakageError with the offending rows named, so the failure is diagnosable
    rather than mysterious.
    """
    if df.empty or time_col not in df.columns:
        return df

    as_of_ts = pd.Timestamp(as_of)
    future_mask = df[time_col] > as_of_ts
    if future_mask.any():
        n = int(future_mask.sum())
        offending = df.loc[future_mask].head(5)
        # Build a readable detail string with row indices and timestamps.
        details = []
        for idx, row in offending.iterrows():
            detail = f"  row {idx}: {time_col}={row[time_col]}"
            if "ticker" in df.columns:
                detail += f", ticker={row['ticker']}"
            details.append(detail)
        detail_str = "\n".join(details)
        src = f" [{source}]" if source else ""
        raise LeakageError(
            f"Future data leak{src}: {n} row(s) have {time_col} > as_of ({as_of_ts}).\n"
            f"Offending rows:\n{detail_str}"
        )
    return df


def assert_raw_prices(df: pd.DataFrame, source: str = "") -> pd.DataFrame:
    """Reject price frames that carry only adjusted values.

    Require raw `open/high/low/close/volume` columns to be present. An `adj_close`
    column MAY exist alongside them, but a frame with adjusted prices and no raw
    prices raises AdjustedPriceError.

    Also reject any frame flagged with `auto_adjust=True` provenance metadata.
    """
    if df.empty:
        return df

    cols_lower = {c.lower() for c in df.columns}

    # Check for auto_adjust metadata attribute (yfinance sets this).
    if getattr(df, "attrs", None) and df.attrs.get("auto_adjust"):
        src = f" [{source}]" if source else ""
        raise AdjustedPriceError(
            f"Price frame{src} has auto_adjust=True metadata. "
            f"Adjusted prices are retroactively restated and leak future corporate actions."
        )

    # Check if raw OHLCV columns are present.
    has_raw = _RAW_OHLCV_COLS.issubset(cols_lower)

    # Check if the frame has adjusted price columns.
    adjusted_indicators = {"adj_close", "adj close", "adjusted_close", "adjusted close"}
    has_adjusted = bool(adjusted_indicators & cols_lower)

    if not has_raw:
        src = f" [{source}]" if source else ""
        if has_adjusted:
            raise AdjustedPriceError(
                f"Price frame{src} has adjusted prices but no raw OHLCV columns "
                f"(need: {sorted(_RAW_OHLCV_COLS)}). Adjusted prices are retroactively "
                f"restated on every split/dividend, leaking future corporate actions."
            )
        # No raw OHLCV and no adjusted -- likely not a price frame. Still reject if
        # it looks like it should have prices (has some price-like column).
        price_like = {"price", "close", "adj_close", "open", "high", "low"}
        if price_like & cols_lower:
            raise AdjustedPriceError(
                f"Price frame{src} appears to be a price series but is missing "
                f"raw OHLCV columns (need: {sorted(_RAW_OHLCV_COLS)})."
            )

    return df


def assert_lagged_disclosure(
    df: pd.DataFrame,
    event_col: str,
    filing_col: str,
    min_lag_days: int,
    source: str = "",
) -> pd.DataFrame:
    """Verify a lagged-disclosure dataset uses filing dates and respects the statutory lag.

    Checks that `available_at` derives from `filing_col`, not `event_col`, and that
    `filing_col - event_col` is plausible for the source:
      13F: 45 days . STOCK Act PTR: 45 days . FINRA short interest: ~11 business days.

    A dataset where available_at tracks the event date is look-ahead wearing a disguise,
    and it is the single most common way this class of data corrupts a backtest.
    """
    if df.empty:
        return df

    for col in (event_col, filing_col, "available_at"):
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col!r}")

    # Convert to datetime for comparison.
    event_ts = pd.to_datetime(df[event_col])
    filing_ts = pd.to_datetime(df[filing_col])
    available_ts = pd.to_datetime(df["available_at"])

    # Check 1: available_at should track filing_col, not event_col.
    # Measure closeness: if available_at is closer to event_col than filing_col,
    # the dataset is using the wrong date.
    delta_to_event = (available_ts - event_ts).abs()
    delta_to_filing = (available_ts - filing_ts).abs()

    # A row where available_at is closer to event_col than filing_col is suspect.
    tracks_event = delta_to_event < delta_to_filing
    # Allow small tolerance -- if filing and event are close, it's ambiguous.
    lag_days = (filing_ts - event_ts).dt.days
    # Only flag when there's a meaningful lag between event and filing.
    meaningful_lag = lag_days >= min_lag_days
    violations = tracks_event & meaningful_lag

    if violations.any():
        n = int(violations.sum())
        src = f" [{source}]" if source else ""
        sample = df.loc[violations].head(3)
        details = []
        for idx, row in sample.iterrows():
            details.append(
                f"  row {idx}: {event_col}={row[event_col]}, "
                f"{filing_col}={row[filing_col]}, available_at={row['available_at']}"
            )
        detail_str = "\n".join(details)
        raise LeakageError(
            f"Lagged-disclosure violation{src}: {n} row(s) have available_at tracking "
            f"{event_col} rather than {filing_col} (min lag: {min_lag_days}d).\n"
            f"Sample:\n{detail_str}"
        )

    # Check 2: The lag between event and filing should meet the minimum.
    insufficient_lag = lag_days < min_lag_days
    # Only flag rows where filing is known (not NaT).
    has_both = filing_ts.notna() & event_ts.notna()
    bad_lag = insufficient_lag & has_both

    if bad_lag.any():
        n = int(bad_lag.sum())
        src = f" [{source}]" if source else ""
        median_lag = lag_days[has_both].median()
        raise LeakageError(
            f"Lagged-disclosure lag too short{src}: {n} row(s) have "
            f"{filing_col} - {event_col} < {min_lag_days} days "
            f"(median lag: {median_lag:.0f} days). Data may be using event dates "
            f"as filing dates."
        )

    return df


def _log_violation(
    conn: duckdb.DuckDBPyConnection,
    table_name: str,
    as_of: pd.Timestamp,
    n_rows: int,
    detail: str,
) -> None:
    """Log a violation to the firewall_violations table."""
    conn.execute(
        "INSERT INTO firewall_violations (detected_at, table_name, as_of, n_rows, detail) "
        "VALUES (?, ?, ?, ?, ?)",
        [datetime.now(UTC), table_name, as_of, n_rows, detail],
    )


def audit(conn: duckdb.DuckDBPyConnection, as_of: pd.Timestamp) -> pd.DataFrame:
    """Sweep every table for future-dated rows and lag violations.

    Run by `make leakage-audit` and at the start of every backtest. Returns a frame of
    violations; empty means clean. The count is reported as a process-health metric --
    it should be zero, and a non-zero value invalidates any result computed since.
    """
    as_of_ts = pd.Timestamp(as_of)
    violations: list[dict[str, object]] = []

    for table in _AUDITABLE_TABLES:
        # Check if table exists.
        try:
            result = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE available_at > ?", [as_of_ts]
            ).fetchone()
        except Exception:
            # Table doesn't exist yet -- skip.
            continue

        if result is None:
            continue
        n_future = result[0]
        if n_future > 0:
            detail = f"{n_future} rows have available_at > {as_of_ts}"
            violations.append(
                {
                    "table_name": table,
                    "as_of": as_of_ts,
                    "n_rows": n_future,
                    "detail": detail,
                    "violation_type": "future_data",
                }
            )
            _log_violation(conn, table, as_of_ts, n_future, detail)
            logger.warning("Firewall violation: %s — %s", table, detail)

    # Check lagged-disclosure tables for lag violations.
    _lagged_checks = [
        ("institutional_holdings", "period_end", "filed_at", 45),
        ("political_txns", "txn_date", "filed_at", 45),
        ("short_interest", "settlement_date", "publication_date", 11),
    ]

    for table, event_col, filing_col, min_lag in _lagged_checks:
        try:
            df = (
                conn.execute(f"SELECT * FROM {table} WHERE available_at <= ?", [as_of_ts])
                .fetch_arrow_table()
                .to_pandas()
            )
        except Exception:
            continue

        if df.empty:
            continue

        try:
            assert_lagged_disclosure(df, event_col, filing_col, min_lag, source=table)
        except LeakageError as e:
            detail = str(e)[:500]
            n_rows = len(df)
            violations.append(
                {
                    "table_name": table,
                    "as_of": as_of_ts,
                    "n_rows": n_rows,
                    "detail": detail,
                    "violation_type": "lag_violation",
                }
            )
            _log_violation(conn, table, as_of_ts, n_rows, detail)
            logger.warning("Firewall lag violation: %s — %s", table, detail[:200])

    if violations:
        return pd.DataFrame(violations)
    return pd.DataFrame(columns=["table_name", "as_of", "n_rows", "detail", "violation_type"])
