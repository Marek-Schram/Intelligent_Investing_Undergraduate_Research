"""Almgren-Chriss impact. TICKET-044. docs/13 §2.4."""

from __future__ import annotations

import pytest


@pytest.mark.xfail(reason="TICKET-044")
def test_square_root_scaling():
    """Doubling order size raises temporary impact ~1.41x, not 2x."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-044")
def test_thin_name_costs_more_than_flat_tier_model():
    """A Sleeve E order at 1% of ADV in a thin name must cost materially more than the
    old flat-tier model. Quantify the difference."""
    raise NotImplementedError
