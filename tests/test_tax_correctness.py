"""Tax engine. TICKET-035/036/037. docs/11."""

from __future__ import annotations

import pytest


@pytest.mark.xfail(reason="TICKET-036")
def test_cross_account_wash_sale_detected():
    """Taxable sale + Roth purchase inside the 61-day window must be caught and reported
    as a PERMANENT loss of the deduction, not a deferral. This is the trap that costs
    real money and it is invisible unless you scan every account."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-036")
def test_drip_counts_as_purchase():
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-036")
def test_disallowed_loss_added_to_basis_not_deleted():
    """And the holding period is inherited."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-035")
def test_after_tax_optimal_beats_naive_hifo():
    """Fixture where a short-term small-gain lot costs more than a long-term
    larger-gain lot."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-035")
def test_no_float_in_money_path():
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-037")
def test_tax_alpha_vs_naive_counterfactual():
    raise NotImplementedError
