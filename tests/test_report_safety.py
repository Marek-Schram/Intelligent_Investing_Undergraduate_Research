"""Safety invariants that make unattended scheduling safe."""

from __future__ import annotations

import pytest


@pytest.mark.xfail(reason="TICKET-023")
def test_reporting_never_imports_execution():
    """Import durable.reporting.report in a clean subprocess; assert no module named
    'durable.execution' is present. This proves a scheduled report can never place an
    order, regardless of any future refactor. A PreToolUse hook enforces it at edit time;
    this enforces it at run time."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-035/036")
def test_tax_and_research_never_import_execution():
    """Same guarantee for the tax and research packages."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-023")
def test_no_network_during_report_generation():
    """Monkeypatch socket to raise; a full report must still generate."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-023")
def test_report_is_deterministic():
    """Same snapshot in, byte-identical JSON sidecar out, twice."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-021")
def test_report_raises_on_noncompliant_narrative():
    """A banned phrase must ABORT the write, not warn."""
    raise NotImplementedError


@pytest.mark.xfail(reason="TICKET-019")
def test_deflated_sharpe_raises_without_experiment_log():
    """Missing or empty experiment_log.csv must raise, never default n_trials to 1 —
    defaulting silently inflates every result in the research project."""
    raise NotImplementedError
