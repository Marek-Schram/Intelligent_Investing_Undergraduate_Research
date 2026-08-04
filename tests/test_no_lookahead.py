"""The most important test in the repo. docs/03 §1."""

from __future__ import annotations

import pytest


@pytest.mark.xfail(reason="TICKET-001/002/006")
def test_future_filing_does_not_change_past_scores():
    """Corrupt a filing dated AFTER the as-of date; earlier scores must not move.

    1. Score 2018-06-30 from a fixture DB. Record.
    2. Insert an absurd filing (revenue = 1e15) with available_at = 2018-09-30.
    3. Re-score 2018-06-30. Assert byte-identical.

    If this can pass without a real point-in-time guard, the guard isn't real.
    """
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-001")
def test_available_at_boundary_excludes_future():
    """A row with available_at = as_of + 1 second must be excluded."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-002")
def test_no_restated_values_used():
    """Where an original and a restatement exist, scoring uses the original."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-032")
def test_13f_uses_filed_at_not_period_end():
    """13F carries a 45-day lag. Using period_end is look-ahead by 45 days."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-034")
def test_short_interest_uses_publication_date():
    """FINRA publishes 11+ business days after settlement."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-031/045")
def test_llm_extraction_contamination_guard():
    """Using an extraction before the model's training cutoff must raise unless
    explicitly allowed — the model has read the future (docs/13 §1)."""
    raise NotImplementedError
