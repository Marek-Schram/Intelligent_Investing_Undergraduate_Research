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

import pandas as pd


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
    raise NotImplementedError("TICKET-042")


def assert_raw_prices(df: pd.DataFrame, source: str = "") -> pd.DataFrame:
    """Reject price frames that carry only adjusted values.

    Require raw `open/high/low/close/volume` columns to be present. An `adj_close`
    column MAY exist alongside them, but a frame with adjusted prices and no raw
    prices raises AdjustedPriceError.

    Also reject any frame flagged with `auto_adjust=True` provenance metadata.
    """
    raise NotImplementedError("TICKET-042")


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
      13F: 45 days · STOCK Act PTR: 45 days · FINRA short interest: ~11 business days.

    A dataset where available_at tracks the event date is look-ahead wearing a disguise,
    and it is the single most common way this class of data corrupts a backtest.
    """
    raise NotImplementedError("TICKET-042")


def audit(conn, as_of: pd.Timestamp) -> pd.DataFrame:
    """Sweep every table for future-dated rows and lag violations.

    Run by `make leakage-audit` and at the start of every backtest. Returns a frame of
    violations; empty means clean. The count is reported as a process-health metric --
    it should be zero, and a non-zero value invalidates any result computed since.
    """
    raise NotImplementedError("TICKET-042")
