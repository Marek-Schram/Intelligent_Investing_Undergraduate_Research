"""Sleeve E hard limits. TICKET-024/029/046. docs/08."""

from __future__ import annotations

import pytest


@pytest.mark.xfail(reason="TICKET-024")
def test_otc_always_rejected():
    """Including any ticker OTC-quoted within the trailing 24 months."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-024")
def test_missing_data_excludes_never_imputes():
    """Missing data in a low-coverage name is itself informative."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-024")
def test_safety_constants_not_config_readable():
    """Universe and sizing limits are module constants, not tunable config."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-025")
def test_manipulation_flag_beats_perfect_fundamentals():
    """A perfect durability score with one manipulation flag is still excluded."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-029")
def test_price_decline_alone_never_unlocks_tranche():
    """A 50% drawdown with unchanged fundamentals must NOT make T2 eligible. Averaging
    down into a deteriorating thesis is how a 0.25% position becomes a 2% mistake."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-046")
def test_bear_case_required_for_sleeve_e_buy():
    """Memo generation raises without a bear case and exactly three falsifiers."""
    raise NotImplementedError
