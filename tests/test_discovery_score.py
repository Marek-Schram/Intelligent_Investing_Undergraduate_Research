"""Tests for Sleeve E discovery score. TICKET-028."""

from __future__ import annotations

import pytest

from durable.discovery.score import (
    DURABILITY_GATE_MIN,
    EV_EBIT_EXCLUSION_THRESHOLD,
    GateResult,
    POSITION_THRESHOLD,
    QualityClaim,
    WATCHLIST_THRESHOLD,
    _durability_subscore,
    _quality_subscore,
    _valuation_subscore,
    compute_discovery_score,
)


class TestDurabilityGate:
    """Durability gate before anything else — acceptance criterion."""

    def test_gate_fails_below_30(self):
        """Durability < 30 => immediate rejection, total=0."""
        result = compute_discovery_score(
            "LOW",
            durability_raw=25.0,
            neglect_sub=20,
            ev_ebit=15.0,
            peer_ev_ebits=[12.0, 18.0, 20.0, 25.0, 28.0],
        )
        assert result.total == 0
        assert result.gate_result == GateResult.FAILED_DURABILITY

    def test_gate_fails_none(self):
        result = compute_discovery_score("NONE", durability_raw=None, neglect_sub=25)
        assert result.total == 0
        assert result.gate_result == GateResult.FAILED_DURABILITY

    def test_gate_passes_at_30(self):
        result = compute_discovery_score("PASS", durability_raw=30.0)
        assert result.gate_result == GateResult.PASSED
        assert result.durability_sub == 0  # 30/50 scales to 0/40

    def test_gate_passes_at_50(self):
        result = compute_discovery_score("MAX", durability_raw=50.0)
        assert result.gate_result == GateResult.PASSED
        assert result.durability_sub == 40

    def test_gate_scales_linearly(self):
        result = compute_discovery_score("MID", durability_raw=40.0)
        # (40-30)/(50-30) * 40 = 20
        assert result.durability_sub == 20


class TestSmallCapPeerRanking:
    """Small-cap peer ranking with documented fallback — acceptance criterion."""

    def test_best_valuation_highest_score(self):
        """Cheapest name ranks highest."""
        result = compute_discovery_score(
            "CHEAP",
            durability_raw=40.0,
            ev_ebit=8.0,
            peer_ev_ebits=[10.0, 15.0, 20.0, 25.0, 30.0],
        )
        assert result.valuation_sub == 25  # Best in group

    def test_worst_valuation_lowest_score(self):
        """Most expensive name ranks lowest."""
        result = compute_discovery_score(
            "PRICEY",
            durability_raw=40.0,
            ev_ebit=30.0,
            peer_ev_ebits=[5.0, 10.0, 15.0, 20.0, 25.0],
        )
        assert result.valuation_sub == 0

    def test_fallback_when_few_peers(self):
        """Fallback documented when peer group < 5."""
        result = compute_discovery_score(
            "SMALL_GROUP",
            durability_raw=40.0,
            ev_ebit=10.0,
            peer_ev_ebits=[15.0, 20.0],
        )
        assert result.used_fallback_peers is True
        assert result.peer_group_size == 2


class TestEvEbitExclusion:
    """EV/EBIT > 30 excluded — acceptance criterion."""

    def test_ev_ebit_above_30_excluded(self):
        result = compute_discovery_score(
            "EXPENSIVE",
            durability_raw=45.0,
            neglect_sub=20,
            ev_ebit=31.0,
            peer_ev_ebits=[10.0, 15.0, 20.0, 25.0, 28.0],
        )
        assert result.total == 0
        assert result.gate_result == GateResult.FAILED_VALUATION

    def test_ev_ebit_at_30_allowed(self):
        result = compute_discovery_score(
            "BORDERLINE",
            durability_raw=45.0,
            ev_ebit=30.0,
            peer_ev_ebits=[10.0, 15.0, 20.0, 25.0, 28.0],
        )
        assert result.gate_result == GateResult.PASSED

    def test_ev_ebit_none_allowed(self):
        """Missing EV/EBIT doesn't exclude (but gets 0 valuation points)."""
        result = compute_discovery_score(
            "NODATA",
            durability_raw=45.0,
            ev_ebit=None,
        )
        assert result.gate_result == GateResult.PASSED
        assert result.valuation_sub == 0


class TestUncitedQualityClaims:
    """Uncited quality claims score 0 — acceptance criterion."""

    def test_cited_claims_score(self):
        claims = [
            QualityClaim(claim="recurring revenue", cited=True, points=3),
            QualityClaim(claim="top customer < 20%", cited=True, points=2),
        ]
        result = compute_discovery_score(
            "CITED",
            durability_raw=40.0,
            quality_claims=claims,
        )
        assert result.quality_sub == 5

    def test_uncited_claims_score_zero(self):
        """Uncited quality claims explicitly score 0."""
        claims = [
            QualityClaim(claim="recurring revenue", cited=False, points=3),
            QualityClaim(claim="great management", cited=False, points=2),
        ]
        result = compute_discovery_score(
            "UNCITED",
            durability_raw=40.0,
            quality_claims=claims,
        )
        assert result.quality_sub == 0

    def test_mixed_cited_uncited(self):
        claims = [
            QualityClaim(claim="recurring revenue", cited=True, points=3),
            QualityClaim(claim="moat", cited=False, points=5),
            QualityClaim(claim="insider ownership", cited=True, points=3),
        ]
        result = compute_discovery_score(
            "MIX",
            durability_raw=40.0,
            quality_claims=claims,
        )
        assert result.quality_sub == 6  # Only cited: 3+3=6

    def test_quality_capped_at_10(self):
        claims = [
            QualityClaim(claim="a", cited=True, points=5),
            QualityClaim(claim="b", cited=True, points=5),
            QualityClaim(claim="c", cited=True, points=5),
        ]
        result = compute_discovery_score(
            "CAP",
            durability_raw=40.0,
            quality_claims=claims,
        )
        assert result.quality_sub == 10


class TestThresholds:
    def test_watchlist_at_65(self):
        assert WATCHLIST_THRESHOLD == 65

    def test_position_at_75(self):
        assert POSITION_THRESHOLD == 75

    def test_eligible_properties(self):
        result = compute_discovery_score(
            "HIGH",
            durability_raw=50.0,
            neglect_sub=25,
            ev_ebit=5.0,
            peer_ev_ebits=[10.0, 15.0, 20.0, 25.0, 30.0],
            quality_claims=[QualityClaim("x", True, 10)],
            insider_purchases_90d=3,
            institutional_conviction_count=2,
        )
        # 40 + 25 + 25 + 10 + 5 = 105 -> capped components
        assert result.eligible_position is True
        assert result.eligible_watchlist is True


class TestOverlays:
    def test_insider_and_conviction(self):
        result = compute_discovery_score(
            "OV",
            durability_raw=40.0,
            insider_purchases_90d=3,
            institutional_conviction_count=2,
        )
        assert result.overlay_sub == 5  # 3+2

    def test_no_overlays(self):
        result = compute_discovery_score("PLAIN", durability_raw=40.0)
        assert result.overlay_sub == 0
