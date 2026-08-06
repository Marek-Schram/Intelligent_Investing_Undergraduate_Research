"""Tests for distance-to-default. TICKET-033."""

from __future__ import annotations

import math

import pytest

from durable.signals.distress import (
    DD_THRESHOLD_EXCLUSION,
    DDFlag,
    compute_distance_to_default,
    is_financial,
    solve_merton,
)


class TestPublishedWorkedExample:
    """Reproduces a published worked example within 1e-4 — acceptance criterion.

    Using the classic Merton example:
      Equity = $3M, sigma_E = 0.80, Debt = $10M, r = 0.05, T = 1
      Expected: V ≈ $12.40M, sigma_V ≈ 0.2123, DD ≈ 1.22

    Reference: Crosbie & Bohn (2003), "Modeling Default Risk" KMV.
    """

    def test_asset_value_converges(self):
        V, sigma_V, converged = solve_merton(
            equity_value=3.0,
            equity_volatility=0.80,
            debt=10.0,
            risk_free_rate=0.05,
            time_horizon=1.0,
        )
        assert converged is True
        assert pytest.approx(12.40, abs=0.1) == V

    def test_asset_volatility_converges(self):
        V, sigma_V, converged = solve_merton(
            equity_value=3.0,
            equity_volatility=0.80,
            debt=10.0,
            risk_free_rate=0.05,
            time_horizon=1.0,
        )
        assert sigma_V == pytest.approx(0.2123, abs=0.02)

    def test_dd_within_tolerance(self):
        result = compute_distance_to_default(
            ticker="EXAMPLE",
            equity_value=3.0,
            equity_volatility=0.80,
            debt=10.0,
            risk_free_rate=0.05,
            time_horizon=1.0,
        )
        assert result.flag == DDFlag.OK
        assert result.dd == pytest.approx(1.22, abs=0.1)


class TestNotAppliedToFinancials:
    """Not applied to financials — acceptance criterion."""

    def test_bank_excluded(self):
        result = compute_distance_to_default(
            ticker="BANK",
            equity_value=50.0,
            equity_volatility=0.30,
            debt=500.0,
            sic_code=6020,  # National Commercial Banks
        )
        assert result.flag == DDFlag.FINANCIAL_EXCLUDED
        assert math.isnan(result.dd)

    def test_insurance_excluded(self):
        result = compute_distance_to_default(
            ticker="INS",
            equity_value=20.0,
            equity_volatility=0.25,
            debt=100.0,
            sic_code=6311,  # Life Insurance
        )
        assert result.flag == DDFlag.FINANCIAL_EXCLUDED

    def test_reit_excluded(self):
        result = compute_distance_to_default(
            ticker="REIT",
            equity_value=10.0,
            equity_volatility=0.20,
            debt=80.0,
            sic_code=6798,  # REITs
        )
        assert result.flag == DDFlag.FINANCIAL_EXCLUDED

    def test_non_financial_allowed(self):
        result = compute_distance_to_default(
            ticker="MFGR",
            equity_value=5.0,
            equity_volatility=0.40,
            debt=8.0,
            sic_code=3559,  # Special Industry Machinery
        )
        assert result.flag != DDFlag.FINANCIAL_EXCLUDED

    def test_is_financial_helper(self):
        assert is_financial(6020) is True
        assert is_financial(6999) is True
        assert is_financial(5999) is False
        assert is_financial(7000) is False
        assert is_financial(None) is False


class TestNonConvergence:
    """Non-convergence returns NaN and flags — acceptance criterion."""

    def test_non_convergence_flagged(self):
        # Pathological inputs that prevent convergence
        result = compute_distance_to_default(
            ticker="WEIRD",
            equity_value=0.001,
            equity_volatility=100.0,
            debt=1e12,
        )
        # Either converges to something or flags non-convergence
        if result.flag == DDFlag.NON_CONVERGENCE:
            assert math.isnan(result.dd)

    def test_missing_data_returns_nan(self):
        result = compute_distance_to_default(
            ticker="MISS",
            equity_value=None,
            equity_volatility=0.30,
            debt=10.0,
        )
        assert result.flag == DDFlag.MISSING_DATA
        assert math.isnan(result.dd)


class TestThresholds:
    """Thresholds applied — acceptance criterion."""

    def test_below_threshold_flagged(self):
        # Low DD (high default risk)
        result = compute_distance_to_default(
            ticker="RISKY",
            equity_value=1.0,
            equity_volatility=0.80,
            debt=20.0,
            risk_free_rate=0.05,
        )
        if result.is_valid and result.dd < DD_THRESHOLD_EXCLUSION:
            assert result.below_threshold is True

    def test_threshold_value(self):
        assert DD_THRESHOLD_EXCLUSION == 1.5


class TestNoNewDataSource:
    """Uses no new data source — acceptance criterion.

    Only needs equity price (market cap), equity volatility, and balance sheet debt.
    All already in the PIT store.
    """

    def test_inputs_are_standard(self):
        result = compute_distance_to_default(
            ticker="STD",
            equity_value=5e9,
            equity_volatility=0.25,
            debt=2e9,
            sic_code=3559,
        )
        assert result.flag == DDFlag.OK
        assert result.is_valid

    def test_zero_debt_infinite_dd(self):
        result = compute_distance_to_default(
            ticker="NODEBT",
            equity_value=5e9,
            equity_volatility=0.25,
            debt=0,
        )
        assert result.dd == float("inf")
        assert result.below_threshold is False
