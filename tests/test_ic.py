"""Factor IC analysis. TICKET-043. docs/09 §7."""

from __future__ import annotations

import pytest


@pytest.mark.xfail(reason="TICKET-043")
def test_spearman_not_pearson():
    """On a fat-tailed fixture, Pearson is dominated by two outliers while Spearman is
    stable. That instability is exactly why rank correlation is required."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-043")
def test_suspicious_ic_is_flagged():
    """|mean IC| > 0.15 on real data almost always means look-ahead. The summary must
    flag it loudly and recommend the backtest-validator subagent."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-043")
def test_ic_decay_reproduces_known_half_life():
    """A synthetic factor with a 2-quarter half-life must produce the expected curve."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-043")
def test_non_monotonic_quantiles_reported_as_tail_effect():
    """A fixture with a large top-minus-bottom spread but non-monotonic middle quantiles
    must be reported as a tail effect, NOT quoted as a factor spread."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-043")
def test_sector_bet_detected_by_sector_neutral_ic():
    """A fixture that is purely a sector bet shows strong raw IC and near-zero
    sector-neutral IC."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-043")
def test_ic_run_logged_as_trial():
    """An IC test is a trial and counts toward the Deflated Sharpe trial count."""
    raise NotImplementedError
