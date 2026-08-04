"""CPCV and PBO. TICKET-030. docs/09."""

from __future__ import annotations

import pytest


@pytest.mark.xfail(reason="TICKET-030")
def test_n10_k3_produces_120_paths():
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-030")
def test_purging_removes_overlapping_labels():
    """On a synthetic dataset with deliberately overlapping labels, omitting the purge
    must demonstrably inflate measured performance. If it doesn't, the purge isn't
    doing anything."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-030")
def test_pbo_detects_deliberate_overfit():
    """A fixture strategy fitted to noise must yield PBO > 0.5."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-030")
def test_walk_forward_percentile_reported():
    """The single walk-forward result must be located within the CPCV distribution."""
    raise NotImplementedError
