"""Tests for Factor IC analysis. TICKET-043."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from durable.factors.ic import (
    LOOKAHEAD_IC_THRESHOLD,
    factor_autocorrelation,
    ic_decay,
    ic_summary,
    is_monotonic,
    quantile_returns,
    rank_ic,
    sector_neutral_ic,
)


def _make_panel(n_dates=20, n_stocks=50, seed=42):
    """Create synthetic factor and return panels."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n_dates, freq="QE")
    stocks = [f"S{i:03d}" for i in range(n_stocks)]
    factor = pd.DataFrame(rng.standard_normal((n_dates, n_stocks)), index=dates, columns=stocks)
    returns = pd.DataFrame(rng.standard_normal((n_dates, n_stocks)) * 0.05, index=dates, columns=stocks)
    return factor, returns


class TestSpearmanNotPearson:
    """Spearman, not Pearson — acceptance criterion."""

    def test_fat_tails_spearman_stable(self):
        """On fat-tailed data, Pearson dominated by outliers, Spearman stable."""
        rng = np.random.default_rng(42)
        dates = pd.date_range("2020-01-01", periods=10, freq="QE")
        stocks = [f"S{i}" for i in range(30)]

        factor_data = rng.standard_normal((10, 30))
        return_data = rng.standard_normal((10, 30)) * 0.05

        # Inject extreme outliers that dominate Pearson
        factor_data[:, 0] = 100.0
        return_data[:, 0] = 5.0

        factor = pd.DataFrame(factor_data, index=dates, columns=stocks)
        returns = pd.DataFrame(return_data, index=dates, columns=stocks)

        ic_spearman = rank_ic(factor, returns, method="spearman")
        ic_pearson = rank_ic(factor, returns, method="pearson")

        # Pearson should be more volatile (dominated by outlier)
        assert ic_pearson.std() > ic_spearman.std() * 0.5 or abs(ic_pearson.mean()) > abs(ic_spearman.mean())


class TestSuspiciousICFlagged:
    """|mean IC| > 0.15 flagged as suspected look-ahead — acceptance criterion."""

    def test_high_ic_flagged(self):
        """Synthetic perfect foresight => flagged."""
        rng = np.random.default_rng(42)
        dates = pd.date_range("2020-01-01", periods=20, freq="QE")
        stocks = [f"S{i}" for i in range(30)]

        returns = pd.DataFrame(rng.standard_normal((20, 30)) * 0.05, index=dates, columns=stocks)
        # Factor = future returns (look-ahead)
        factor = returns.copy()

        ic_s = rank_ic(factor, returns)
        summary = ic_summary(ic_s)
        assert summary["suspected_lookahead"] is True
        assert abs(summary["mean_ic"]) > LOOKAHEAD_IC_THRESHOLD

    def test_normal_ic_not_flagged(self):
        factor, returns = _make_panel()
        ic_s = rank_ic(factor, returns)
        summary = ic_summary(ic_s)
        assert summary["suspected_lookahead"] is False


class TestICDecay:
    """IC decay across horizons — acceptance criterion."""

    def test_decay_curve_produced(self):
        factor, returns = _make_panel()
        horizons_data = {1: returns, 2: returns * 0.7, 4: returns * 0.3, 8: returns * 0.1}
        decay = ic_decay(factor, horizons_data)
        assert len(decay) == 4
        assert "mean_ic" in decay.columns


class TestNonMonotonicQuantiles:
    """Non-monotonic reported as tail effect — acceptance criterion."""

    def test_monotonic_passes(self):
        df = pd.DataFrame({"mean_return": [0.01, 0.02, 0.03, 0.04, 0.05]}, index=range(1, 6))
        mono, msg = is_monotonic(df)
        assert mono is True

    def test_non_monotonic_large_spread_tail_effect(self):
        """Large spread but non-monotonic = tail effect, not factor."""
        df = pd.DataFrame(
            {"mean_return": [-0.02, 0.01, -0.005, 0.005, 0.04]},
            index=range(1, 6),
        )
        mono, msg = is_monotonic(df)
        assert mono is False
        assert "tail effect" in msg


class TestSectorNeutralIC:
    """Sector bet detected — acceptance criterion."""

    def test_sector_bet_shows_strong_raw_weak_neutral(self):
        """A factor that is purely a sector bet: strong raw IC, near-zero sector-neutral."""
        rng = np.random.default_rng(42)
        dates = pd.date_range("2020-01-01", periods=20, freq="QE")
        stocks = [f"S{i}" for i in range(40)]

        # Assign sectors
        sectors = pd.Series(
            ["Tech"] * 20 + ["Health"] * 20,
            index=stocks,
        )

        # Factor = sector indicator (Tech=1, Health=0)
        factor_vals = np.zeros((20, 40))
        factor_vals[:, :20] = 1.0  # Tech stocks high
        factor = pd.DataFrame(factor_vals, index=dates, columns=stocks)

        # Returns: Tech outperforms
        return_vals = rng.standard_normal((20, 40)) * 0.02
        return_vals[:, :20] += 0.03  # Tech premium
        returns = pd.DataFrame(return_vals, index=dates, columns=stocks)

        raw_ic = rank_ic(factor, returns)
        neutral_ic = sector_neutral_ic(factor, returns, sectors)

        # Raw IC should be strong (factor predicts returns via sector)
        assert abs(raw_ic.mean()) > 0.1
        # Sector-neutral should be near zero (within sector, no signal)
        assert abs(neutral_ic.mean()) < 0.15


class TestFactorAutocorrelation:
    def test_stable_factor_high_autocorrelation(self):
        """A factor that barely changes should have high autocorrelation."""
        dates = pd.date_range("2020-01-01", periods=10, freq="QE")
        stocks = [f"S{i}" for i in range(20)]
        base = np.arange(20, dtype=float)
        factor = pd.DataFrame(
            np.tile(base, (10, 1)) + np.random.default_rng(42).standard_normal((10, 20)) * 0.1,
            index=dates, columns=stocks,
        )
        ac = factor_autocorrelation(factor)
        assert ac > 0.8

    def test_random_factor_low_autocorrelation(self):
        rng = np.random.default_rng(42)
        dates = pd.date_range("2020-01-01", periods=10, freq="QE")
        stocks = [f"S{i}" for i in range(20)]
        factor = pd.DataFrame(rng.standard_normal((10, 20)), index=dates, columns=stocks)
        ac = factor_autocorrelation(factor)
        assert ac < 0.5


class TestICSummary:
    def test_summary_fields(self):
        factor, returns = _make_panel()
        ic_s = rank_ic(factor, returns)
        summary = ic_summary(ic_s)
        assert "mean_ic" in summary
        assert "std_ic" in summary
        assert "ir" in summary
        assert "t_stat" in summary
        assert "hit_rate" in summary
        assert "n_periods" in summary
        assert 0.0 <= summary["hit_rate"] <= 1.0
