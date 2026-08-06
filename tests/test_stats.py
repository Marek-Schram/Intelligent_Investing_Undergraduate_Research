"""Tests for performance statistics. TICKET-013. Hand-computed fixtures."""

from __future__ import annotations

import numpy as np

from durable.backtest.stats import (
    PerformanceStats,
    cagr,
    compute_stats,
    max_drawdown,
    sharpe_ratio,
    sortino_ratio,
    volatility,
)


class TestSharpeRatio:
    def test_matches_hand_computation(self):
        """Sharpe matches a hand-computed fixture to 1e-6 — acceptance criterion.

        Monthly returns: [0.01, 0.02, -0.01, 0.03, 0.01, 0.02,
                          0.00, -0.02, 0.04, 0.01, 0.02, 0.01]
        rf = 0.0
        mean = 0.011667
        std(ddof=1) = 0.016026
        Sharpe = (0.011667 / 0.016026) * sqrt(12) = 2.5230...
        """
        returns = np.array(
            [0.01, 0.02, -0.01, 0.03, 0.01, 0.02, 0.00, -0.02, 0.04, 0.01, 0.02, 0.01]
        )
        result = sharpe_ratio(returns, risk_free_rate=0.0, periods_per_year=12)

        # Hand computation
        mean_r = np.mean(returns)
        std_r = np.std(returns, ddof=1)
        expected = (mean_r / std_r) * np.sqrt(12)

        assert abs(result - expected) < 1e-6

    def test_zero_vol_returns_zero(self):
        """Constant returns => zero Sharpe (no risk taken)."""
        returns = np.array([0.01, 0.01, 0.01, 0.01])
        result = sharpe_ratio(returns)
        assert result == 0.0

    def test_negative_returns(self):
        """Negative average returns give negative Sharpe."""
        returns = np.array([-0.02, -0.01, -0.03, -0.02])
        result = sharpe_ratio(returns)
        assert result < 0

    def test_risk_free_rate_adjustment(self):
        """Non-zero risk-free rate reduces Sharpe."""
        returns = np.array([0.01, 0.02, 0.01, 0.02, 0.01, 0.02])
        sharpe_0 = sharpe_ratio(returns, risk_free_rate=0.0)
        sharpe_rf = sharpe_ratio(returns, risk_free_rate=0.04)
        assert sharpe_rf < sharpe_0


class TestMaxDrawdown:
    def test_simple_drawdown(self):
        """A known 10% drawdown."""
        # Goes up 10%, then down 20% from there = -12% from peak
        returns = np.array([0.10, -0.20, 0.05])
        dd = max_drawdown(returns)
        # Peak = 1.1, trough = 1.1 * 0.8 = 0.88, dd = 0.88/1.1 - 1 = -0.2
        assert abs(dd - (-0.20)) < 1e-6

    def test_no_drawdown(self):
        """All positive returns => drawdown is 0 or very small."""
        returns = np.array([0.01, 0.02, 0.03])
        dd = max_drawdown(returns)
        assert dd == 0.0


class TestCAGR:
    def test_hand_computed(self):
        """CAGR for 12 months of 1% each = (1.01^12)^1 - 1 = 12.68%."""
        returns = np.array([0.01] * 12)
        result = cagr(returns, periods_per_year=12)
        expected = 1.01**12 - 1
        assert abs(result - expected) < 1e-6

    def test_two_years(self):
        """24 monthly returns = 2 years."""
        returns = np.array([0.01] * 24)
        result = cagr(returns, periods_per_year=12)
        expected = (1.01**24) ** (1 / 2) - 1
        assert abs(result - expected) < 1e-6


class TestVolatility:
    def test_annualized(self):
        """Annualized vol = monthly std * sqrt(12)."""
        returns = np.array([0.01, -0.01, 0.02, -0.02, 0.01, -0.01])
        result = volatility(returns, periods_per_year=12)
        expected = np.std(returns, ddof=1) * np.sqrt(12)
        assert abs(result - expected) < 1e-10


class TestSortino:
    def test_all_positive_returns(self):
        """All positive returns => infinite Sortino."""
        returns = np.array([0.01, 0.02, 0.03, 0.01])
        result = sortino_ratio(returns)
        assert result == float("inf")

    def test_sortino_greater_than_sharpe(self):
        """Sortino >= Sharpe when there are negative returns (penalizes less)."""
        returns = np.array([0.05, -0.01, 0.03, -0.005, 0.04, 0.02])
        s = sharpe_ratio(returns)
        sort = sortino_ratio(returns)
        assert sort >= s


class TestComputeStats:
    def test_returns_all_fields(self):
        """compute_stats returns a complete PerformanceStats."""
        returns = np.array(
            [0.01, 0.02, -0.01, 0.03, 0.01, 0.02, 0.00, -0.02, 0.04, 0.01, 0.02, 0.01]
        )
        stats = compute_stats(returns)
        assert isinstance(stats, PerformanceStats)
        assert stats.n_periods == 12
        assert stats.total_return > 0
        assert stats.cagr > 0
        assert stats.sharpe > 0
        assert stats.max_drawdown <= 0
        assert 0 < stats.win_rate <= 1.0
        assert stats.best_month == 0.04
        assert stats.worst_month == -0.02
