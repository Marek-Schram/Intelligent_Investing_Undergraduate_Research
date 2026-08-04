"""LLM contamination / alpha decay. TICKET-045. docs/13 §1."""

from __future__ import annotations

import pytest


@pytest.mark.xfail(reason="TICKET-045")
def test_contaminated_verdict_on_synthetic_leak():
    """A feature constructed to perform well only before the cutoff must be verdicted
    'contaminated'."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-045")
def test_insufficient_data_verdict():
    """Fewer than 8 periods either side => 'insufficient_data'. Say so; do not guess."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-045")
def test_clean_verdict_wording():
    """'clean' must be documented as 'we looked and found no evidence', never 'proven
    clean'. Asserted because this wording will be quoted in the paper."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-045")
def test_placebo_shuffle_detects_panel_artifact():
    """Shuffled-label IC comparable to real IC means the signal is an artifact of panel
    structure, not the companies."""
    raise NotImplementedError
