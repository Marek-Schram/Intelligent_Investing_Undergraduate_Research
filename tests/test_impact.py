"""Tests for Almgren-Chriss market impact. TICKET-044."""

from __future__ import annotations

import math

import pytest

from durable.backtest.impact import (
    ALPHA,
    ETA,
    GAMMA,
    participation_rate,
    permanent_impact,
    temporary_impact,
    total_cost_bps,
)


class TestSquareRootScaling:
    """Doubling size raises temp cost ~1.41x, not 2x — acceptance criterion."""

    def test_doubling_participation(self):
        """sqrt(2) ≈ 1.414 scaling."""
        vol = 0.30
        cost_1 = temporary_impact(0.01, vol)
        cost_2 = temporary_impact(0.02, vol)
        ratio = cost_2 / cost_1
        assert ratio == pytest.approx(math.sqrt(2), rel=0.001)

    def test_not_linear(self):
        """Verify it's NOT 2x (linear would be wrong)."""
        vol = 0.25
        cost_1 = temporary_impact(0.005, vol)
        cost_2 = temporary_impact(0.010, vol)
        ratio = cost_2 / cost_1
        assert ratio < 1.5  # sqrt(2) ≈ 1.414, not 2.0


class TestPermanentImpactLinear:
    """Permanent impact is linear and does not revert — acceptance criterion."""

    def test_linear_scaling(self):
        vol = 0.30
        cost_1 = permanent_impact(0.01, vol)
        cost_2 = permanent_impact(0.02, vol)
        ratio = cost_2 / cost_1
        assert ratio == pytest.approx(2.0, rel=1e-6)

    def test_doubles_with_participation(self):
        vol = 0.25
        assert permanent_impact(0.04, vol) == pytest.approx(
            permanent_impact(0.02, vol) * 2, rel=1e-6
        )


class TestTotalCostBps:
    """total_cost_bps = half-spread + temporary + permanent — acceptance criterion."""

    def test_includes_all_components(self):
        cost = total_cost_bps(
            shares=1000, price=50.0, adv_shares=100_000,
            volatility=0.30, half_spread_bps=5.0,
        )
        # participation = 1000/100000 = 0.01
        part = 0.01
        expected_temp = ETA * 0.30 * (part ** ALPHA) * 10_000
        expected_perm = GAMMA * 0.30 * part * 10_000
        expected_total = 5.0 + expected_temp + expected_perm
        assert cost == pytest.approx(expected_total, rel=1e-6)

    def test_multiplier_scales(self):
        cost_1x = total_cost_bps(1000, 50, 100_000, 0.30, 5.0, multiplier=1.0)
        cost_2x = total_cost_bps(1000, 50, 100_000, 0.30, 5.0, multiplier=2.0)
        assert cost_2x == pytest.approx(cost_1x * 2, rel=1e-6)


class TestThinNameCostsMore:
    """Sleeve E thin name costs more than flat-tier — acceptance criterion."""

    def test_thin_vs_liquid(self):
        """1% of ADV in a thin name vs a liquid name."""
        # Thin name: ADV = 50K shares, buying 500 shares (1%)
        thin_cost = total_cost_bps(500, 25.0, 50_000, 0.40, 10.0)

        # Liquid name: ADV = 5M shares, buying 50K shares (1%)
        liquid_cost = total_cost_bps(50_000, 100.0, 5_000_000, 0.20, 2.0)

        # Thin name should cost materially more
        assert thin_cost > liquid_cost
        assert thin_cost > liquid_cost * 2  # "materially" more

    def test_vs_flat_tier_model(self):
        """A thin Sleeve E name with wide spread costs materially more than
        a flat 5bps model would assume for a liquid large-cap."""
        flat_large_cap_bps = 5.0  # Naive flat assumption for liquid names

        # Sleeve E: thin name, wide spread, volatile
        sleeve_e_cost = total_cost_bps(
            shares=5000, price=30.0, adv_shares=100_000,
            volatility=0.50, half_spread_bps=12.0,
        )
        # The model correctly shows thin names cost more than the flat assumption
        assert sleeve_e_cost > flat_large_cap_bps * 2


class TestParticipationRate:
    def test_calculation(self):
        assert participation_rate(1000, 100_000) == pytest.approx(0.01)

    def test_zero_adv(self):
        assert participation_rate(1000, 0) == 1.0


class TestCoefficientsPublished:
    """Coefficients published — acceptance criterion."""

    def test_constants_exist(self):
        assert ETA == 2.5e-6
        assert GAMMA == 2.5e-7
        assert ALPHA == 0.5
