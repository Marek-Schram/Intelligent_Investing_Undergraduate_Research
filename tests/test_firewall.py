"""Leakage firewall. TICKET-042. docs/13 §2.2."""

from __future__ import annotations

import pytest


@pytest.mark.xfail(reason="TICKET-042")
def test_assert_no_future_raises_and_names_rows():
    """Any available_at > as_of raises LeakageError, naming the offending rows so the
    failure is diagnosable rather than mysterious."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-042")
def test_adjusted_only_prices_rejected():
    """A frame with adj_close and no raw OHLCV raises AdjustedPriceError."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-042")
def test_adjusted_series_differs_from_historical_after_split():
    """The reason the rule exists: construct a fixture with a split, show that today's
    adjusted series does NOT equal the series that existed before the split, and that
    using it leaks the corporate action backwards."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-042")
def test_lagged_disclosure_using_event_date_is_caught():
    """A 13F frame whose available_at tracks period_end rather than filed_at must be
    flagged. Same for STOCK Act PTRs and FINRA short interest."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-042")
def test_every_public_data_function_calls_firewall():
    """Grep the data package: every public function returning a frame must end with a
    firewall call. The store is the primary guard; this catches paths that bypass it."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-042")
def test_leakage_error_is_assertion_error():
    """Deliberately an AssertionError subclass — it must never be caught and handled."""
    raise NotImplementedError
