"""No-trade band and turnover control. TICKET-048."""

from __future__ import annotations

import pytest


@pytest.mark.xfail(reason="TICKET-048")
def test_drift_turnover_without_band():
    """Regression: with no band, forcing positions back to equal weight each quarter
    generates ~37pp of annualized turnover on its own, before any name changes."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-048")
def test_band_cuts_drift_turnover():
    """A 3% band reduces drift turnover to ~7pp with no material performance cost."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-048")
def test_name_changes_ignore_the_band():
    """Entries and exits always execute. Only rebalancing toward equal weight is banded."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-048")
def test_projected_turnover_checked_before_trading():
    """Above the 60% ceiling, the rebalance must reduce to name changes and constraint
    breaches. A kill criterion with no control mechanism is a post-mortem, not a control."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-048")
def test_buffer_rank_justified_by_constraint_not_returns():
    """Buffer rank 80 is chosen on the turnover constraint. The measured CAGR sweep across
    ranks 55-105 was NON-MONOTONIC (7.36/6.62/8.59/6.58/8.13%) — noise. This test documents
    that no return benefit may be claimed for the value."""
    raise NotImplementedError
