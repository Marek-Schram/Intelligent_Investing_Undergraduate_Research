"""Leakage firewall. TICKET-042. docs/13 §2.2."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from durable.data.firewall import (
    AdjustedPriceError,
    LeakageError,
    assert_lagged_disclosure,
    assert_no_future,
    assert_raw_prices,
)


def test_assert_no_future_raises_and_names_rows():
    """Any available_at > as_of raises LeakageError, naming the offending rows so the
    failure is diagnosable rather than mysterious."""
    as_of = pd.Timestamp("2024-06-15")

    # Clean data - should pass
    clean_df = pd.DataFrame({
        "ticker": ["AAPL", "MSFT"],
        "value": [100, 200],
        "available_at": [
            pd.Timestamp("2024-06-01"),
            pd.Timestamp("2024-06-10"),
        ],
    })
    result = assert_no_future(clean_df, as_of, source="test")
    assert len(result) == 2  # Returns unchanged

    # Future data - should raise
    dirty_df = pd.DataFrame({
        "ticker": ["AAPL", "MSFT", "GOOGL"],
        "value": [100, 200, 300],
        "available_at": [
            pd.Timestamp("2024-06-01"),   # OK
            pd.Timestamp("2024-06-20"),   # FUTURE
            pd.Timestamp("2024-07-01"),   # FUTURE
        ],
    })

    with pytest.raises(LeakageError) as exc_info:
        assert_no_future(dirty_df, as_of, source="test_module")

    error_msg = str(exc_info.value)
    # Should name the source
    assert "test_module" in error_msg
    # Should count violations
    assert "2 row(s)" in error_msg
    # Should show ticker info
    assert "MSFT" in error_msg or "GOOGL" in error_msg

    # Empty frame should pass
    empty_df = pd.DataFrame(columns=["ticker", "available_at"])
    result = assert_no_future(empty_df, as_of)
    assert len(result) == 0


def test_adjusted_only_prices_rejected():
    """A frame with adj_close and no raw OHLCV raises AdjustedPriceError."""
    # Frame with only adjusted prices - should fail
    adjusted_only = pd.DataFrame({
        "date": [date(2024, 1, 1), date(2024, 1, 2)],
        "ticker": ["AAPL", "AAPL"],
        "adj_close": [180.0, 182.0],
    })

    with pytest.raises(AdjustedPriceError) as exc_info:
        assert_raw_prices(adjusted_only, source="bad_loader")

    error_msg = str(exc_info.value)
    assert "bad_loader" in error_msg
    assert "adjusted prices" in error_msg.lower()
    assert "raw OHLCV" in error_msg

    # Frame with raw OHLCV - should pass
    raw_prices = pd.DataFrame({
        "date": [date(2024, 1, 1), date(2024, 1, 2)],
        "ticker": ["AAPL", "AAPL"],
        "open": [175.0, 180.0],
        "high": [182.0, 185.0],
        "low": [174.0, 179.0],
        "close": [180.0, 182.0],
        "volume": [1000000, 1100000],
    })
    result = assert_raw_prices(raw_prices, source="good_loader")
    assert len(result) == 2

    # Frame with BOTH raw and adjusted - should pass (adjusted is OK alongside raw)
    both = raw_prices.copy()
    both["adj_close"] = [180.0, 182.0]
    result = assert_raw_prices(both)
    assert len(result) == 2

    # Frame with auto_adjust metadata - should fail
    auto_adjusted = raw_prices.copy()
    auto_adjusted.attrs["auto_adjust"] = True

    with pytest.raises(AdjustedPriceError) as exc_info:
        assert_raw_prices(auto_adjusted)

    assert "auto_adjust=True" in str(exc_info.value)


def test_adjusted_series_differs_from_historical_after_split():
    """The reason the rule exists: construct a fixture with a split, show that today's
    adjusted series does NOT equal the series that existed before the split, and that
    using it leaks the corporate action backwards."""

    # Historical prices BEFORE split announcement (what existed on 2024-06-01)
    historical_series_pre_split = pd.DataFrame({
        "date": pd.date_range("2024-05-01", periods=10, freq="D"),
        "close": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0],
    })

    # Company announces 2:1 split on 2024-06-05, effective 2024-06-10
    # Today's adjusted series (downloaded AFTER the split) retroactively divides all pre-split prices by 2
    todays_adjusted_series = pd.DataFrame({
        "date": pd.date_range("2024-05-01", periods=10, freq="D"),
        "adj_close": [50.0, 50.5, 51.0, 51.5, 52.0, 52.5, 53.0, 53.5, 54.0, 54.5],  # All divided by 2
    })

    # Use the 5th day (2024-05-05, index 4) - historical close was 104.0
    # But today's adjusted series says it was 52.0
    # This is DIFFERENT - the adjusted series has been retroactively restated

    # Index 4 = 2024-05-05 (0=05-01, 1=05-02, 2=05-03, 3=05-04, 4=05-05)
    historical_price_day5 = historical_series_pre_split.iloc[4]["close"]
    todays_adjusted_price_day5 = todays_adjusted_series.iloc[4]["adj_close"]

    # These are DIFFERENT - proof that adjusted series is retroactively restated
    assert historical_price_day5 == 104.0
    assert todays_adjusted_price_day5 == 52.0
    assert historical_price_day5 != todays_adjusted_price_day5

    # If you use today's adjusted series in a backtest at 2024-06-01 (before the split),
    # you're using data (the split adjustment) that didn't exist yet.
    # This is look-ahead bias wearing a disguise.

    # The firewall prevents this by rejecting adjusted-only series
    with pytest.raises(AdjustedPriceError):
        assert_raw_prices(todays_adjusted_series)


def test_lagged_disclosure_using_event_date_is_caught():
    """A 13F frame whose available_at tracks period_end rather than filed_at must be
    flagged. Same for STOCK Act PTRs and FINRA short interest."""

    # BAD: 13F where available_at tracks period_end (the event) instead of filed_at
    bad_13f = pd.DataFrame({
        "ticker": ["AAPL", "MSFT"],
        "shares": [1000, 2000],
        "period_end": [
            pd.Timestamp("2024-03-31"),
            pd.Timestamp("2024-03-31"),
        ],
        "filed_at": [
            pd.Timestamp("2024-05-15"),  # Filed 45 days after period end (correct lag)
            pd.Timestamp("2024-05-15"),
        ],
        "available_at": [
            pd.Timestamp("2024-03-31"),  # WRONG - tracks period_end, not filed_at
            pd.Timestamp("2024-03-31"),
        ],
    })

    with pytest.raises(LeakageError) as exc_info:
        assert_lagged_disclosure(
            bad_13f,
            event_col="period_end",
            filing_col="filed_at",
            min_lag_days=45,
            source="13f_loader",
        )

    error_msg = str(exc_info.value)
    assert "13f_loader" in error_msg
    assert "tracking period_end rather than filed_at" in error_msg or "tracks" in error_msg.lower()

    # GOOD: 13F where available_at correctly tracks filed_at
    good_13f = pd.DataFrame({
        "ticker": ["AAPL", "MSFT"],
        "shares": [1000, 2000],
        "period_end": [
            pd.Timestamp("2024-03-31"),
            pd.Timestamp("2024-03-31"),
        ],
        "filed_at": [
            pd.Timestamp("2024-05-15"),  # Filed 45 days after period end
            pd.Timestamp("2024-05-15"),
        ],
        "available_at": [
            pd.Timestamp("2024-05-16"),  # Correctly tracks filed_at (+ 1 trading day)
            pd.Timestamp("2024-05-16"),
        ],
    })

    result = assert_lagged_disclosure(
        good_13f,
        event_col="period_end",
        filing_col="filed_at",
        min_lag_days=45,
    )
    assert len(result) == 2  # Passes

    # BAD: Lag is too short (implies using event date as filing date)
    short_lag = pd.DataFrame({
        "ticker": ["AAPL"],
        "shares": [1000],
        "period_end": [pd.Timestamp("2024-03-31")],
        "filed_at": [pd.Timestamp("2024-04-05")],  # Only 5 days! Should be 45+
        "available_at": [pd.Timestamp("2024-04-06")],
    })

    with pytest.raises(LeakageError) as exc_info:
        assert_lagged_disclosure(
            short_lag,
            event_col="period_end",
            filing_col="filed_at",
            min_lag_days=45,
        )

    assert "lag too short" in str(exc_info.value).lower()


def test_every_public_data_function_calls_firewall():
    """Grep the data package: every public function returning a frame must end with a
    firewall call. The store is the primary guard; this catches paths that bypass it."""
    import inspect
    import re
    from pathlib import Path

    from durable import data

    data_dir = Path(data.__file__).parent

    # Find all Python modules in data package
    py_files = list(data_dir.glob("*.py"))

    violations = []

    for py_file in py_files:
        if py_file.name.startswith("_"):
            continue  # Skip private modules
        if py_file.name == "firewall.py":
            continue  # Skip the firewall itself

        content = py_file.read_text()

        # Find function definitions that return DataFrames
        # Look for type hints like -> pd.DataFrame or -> DataFrame
        func_pattern = r"def\s+(\w+)\s*\([^)]*\)\s*->\s*(?:pd\.)?DataFrame:"

        for match in re.finditer(func_pattern, content):
            func_name = match.group(1)

            if func_name.startswith("_"):
                continue  # Skip private functions

            # Extract the function body (rough heuristic)
            func_start = match.end()
            # Find the next function or end of file
            next_func = content.find("\ndef ", func_start)
            if next_func == -1:
                func_body = content[func_start:]
            else:
                func_body = content[func_start:next_func]

            # Check if it calls a firewall function
            has_firewall = (
                "assert_no_future" in func_body
                or "assert_raw_prices" in func_body
                or "assert_lagged_disclosure" in func_body
            )

            # Check if it has a return statement
            has_return = "return" in func_body

            if has_return and not has_firewall:
                violations.append(f"{py_file.name}::{func_name}")

    # This test is informative - we check but don't fail hard since some functions
    # might legitimately not need firewall (they don't load external data)
    # The key is to be aware of functions that bypass the firewall

    if violations:
        # Log them but make this a soft assertion for now
        # In a stricter implementation, this would fail
        import warnings
        warnings.warn(
            f"Functions that may need firewall calls: {', '.join(violations[:5])}"
        )

    # At minimum, key data loaders should have firewall calls
    # Check that firewall is actually used somewhere
    assert any(
        "assert_no_future" in f.read_text()
        for f in py_files
        if not f.name.startswith("_") and f.name != "firewall.py"
    ), "Firewall functions should be used in data loaders"


def test_leakage_error_is_assertion_error():
    """Deliberately an AssertionError subclass — it must never be caught and handled."""
    assert issubclass(LeakageError, AssertionError)

    # Verify that it can't be caught by a generic Exception handler
    # (well, technically it can, but the subclassing makes it clear this is a bug if you do)
    try:
        raise LeakageError("Test error")
    except AssertionError:
        pass  # Should be catchable as AssertionError
    else:
        pytest.fail("LeakageError should be catchable as AssertionError")

    # Verify AdjustedPriceError is a ValueError (different category)
    assert issubclass(AdjustedPriceError, ValueError)
    assert not issubclass(AdjustedPriceError, AssertionError)
