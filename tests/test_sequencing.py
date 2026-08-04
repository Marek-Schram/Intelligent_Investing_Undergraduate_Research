"""Execution sequencing. TICKET-047. Regression tests from the trading simulation."""

from __future__ import annotations

import pytest


@pytest.mark.xfail(reason="TICKET-047")
def test_cash_never_negative_regression():
    """THE regression test. The simulation fixture that produced 11 negative-cash quarters
    out of 54 under single-pass execution must produce 0 under sequencing."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-047")
def test_cash_buffer_alone_does_not_fix_it():
    """Documents WHY sequencing is architectural rather than a parameter. Buffers of
    0.5/1.0/1.5/2.0% gave 4/4/7/8 negative quarters — larger buffers were worse. This test
    exists so nobody 'simplifies' the sequencer back into a buffer."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-047")
def test_buys_scale_pro_rata_not_priority():
    """When cash is short, ALL buys scale down together. Funding top-ranked names first
    would concentrate the portfolio precisely in tight-cash quarters — a risk change
    disguised as an execution detail."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-047")
def test_cost_reserved_on_buy_side():
    """affordable = cash / (1 + cost_rate). Spending all cash on notional leaves nothing
    for spread and slippage, which is the original bug."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-047")
def test_sell_without_lot_ids_raises():
    raise NotImplementedError
