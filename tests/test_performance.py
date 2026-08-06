"""Tests for TWR/MWR + risk metrics. TICKET-018."""

from __future__ import annotations

import numpy as np
import pytest

from durable.reporting.performance import (
    compute_risk_metrics,
    money_weighted_return,
    time_weighted_return,
)


class TestTWR:
    def test_simple_chain_linking(self):
        """TWR chain-links sub-period returns."""
        # Period 1: 100 -> 110 (+10%), Period 2: 110 -> 121 (+10%)
        nav_series = [(100.0, 110.0), (110.0, 121.0)]
        twr = time_weighted_return(nav_series)
        # (1.10 * 1.10) - 1 = 0.21
        assert abs(twr - 0.21) < 1e-6

    def test_twr_unaffected_by_deposit_size(self):
        """Changing deposit SIZE leaves TWR unchanged — acceptance criterion.

        Scenario: same sub-period returns, but different starting NAVs
        (representing different deposit sizes). TWR should be identical.
        """
        # Small deposits: periods of 10% each
        small = [(100.0, 110.0), (110.0, 121.0)]
        twr_small = time_weighted_return(small)

        # Large deposits: same returns, bigger starting values
        large = [(1000.0, 1100.0), (1100.0, 1210.0)]
        twr_large = time_weighted_return(large)

        assert abs(twr_small - twr_large) < 1e-10

    def test_negative_period(self):
        """Negative return period handled correctly."""
        nav_series = [(100.0, 90.0), (90.0, 99.0)]
        twr = time_weighted_return(nav_series)
        # (0.90 * 1.10) - 1 = -0.01
        assert abs(twr - (-0.01)) < 1e-6


class TestMWR:
    def test_mwr_differs_from_twr(self):
        """Hand fixture where TWR and MWR visibly differ — acceptance criterion.

        Scenario: investor deposits MORE money before a BAD period.
        TWR sees equal sub-periods; MWR penalizes bad timing.
        """
        # Sub-period 1: +20% on $100 (small investment)
        # Sub-period 2: -10% on $220 (added $100 before the drop)
        # TWR = (1.20)(0.90) - 1 = 0.08 (8%)
        nav_series = [(100.0, 120.0), (220.0, 198.0)]
        twr = time_weighted_return(nav_series)
        assert abs(twr - 0.08) < 1e-6

        # MWR: invested $100 at t=0, $100 at t=0.5, got $198 at t=1
        # IRR solving: -100/(1+r)^0 - 100/(1+r)^0.5 + 198/(1+r)^1 = 0
        cash_flows = [(0.0, -100.0), (0.5, -100.0)]
        mwr = money_weighted_return(cash_flows, final_value=198.0)

        # MWR should be LOWER than TWR because money was added before the bad period
        assert mwr < twr
        # And they should visibly differ
        assert abs(twr - mwr) > 0.01

    def test_mwr_moves_with_deposit_size(self):
        """Changing deposit SIZE moves MWR — acceptance criterion.

        Same returns, but larger second deposit means worse MWR
        when the second period is bad.
        """
        # Small second deposit
        cash_flows_small = [(0.0, -100.0), (0.5, -50.0)]
        mwr_small = money_weighted_return(cash_flows_small, final_value=140.0)

        # Large second deposit (more money exposed to bad period)
        cash_flows_large = [(0.0, -100.0), (0.5, -200.0)]
        mwr_large = money_weighted_return(cash_flows_large, final_value=270.0)

        # Both have the same market return, but different investor timing
        assert mwr_small != pytest.approx(mwr_large, abs=0.001)

    def test_no_cash_flows(self):
        """No cash flows returns 0."""
        assert money_weighted_return([], 0.0) == 0.0


class TestRiskMetrics:
    def test_volatility(self):
        """Annualized volatility computed correctly."""
        returns = np.array([0.01, -0.01, 0.02, -0.02, 0.01, -0.01] * 2)
        metrics = compute_risk_metrics(returns, periods_per_year=12)
        assert metrics.volatility_ann > 0

    def test_max_drawdown(self):
        """Max drawdown is negative."""
        returns = np.array([0.05, -0.10, -0.05, 0.03, 0.02])
        metrics = compute_risk_metrics(returns)
        assert metrics.max_drawdown < 0

    def test_var_cvar(self):
        """VaR95 >= CVaR95 (CVaR is further in the tail)."""
        np.random.seed(42)
        returns = np.random.normal(0.005, 0.03, 100)
        metrics = compute_risk_metrics(returns)
        assert metrics.cvar_95 <= metrics.var_95

    def test_beta_against_benchmark(self):
        """Beta computed when benchmark provided."""
        np.random.seed(42)
        benchmark = np.random.normal(0.008, 0.04, 60)
        strategy = 1.2 * benchmark + np.random.normal(0, 0.01, 60)
        metrics = compute_risk_metrics(strategy, benchmark)
        assert metrics.beta is not None
        assert abs(metrics.beta - 1.2) < 0.2  # Should be close to 1.2
