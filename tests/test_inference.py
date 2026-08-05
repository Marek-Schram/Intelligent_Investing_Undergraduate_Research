"""Tests for statistical inference. TICKET-019."""

from __future__ import annotations

import math

import numpy as np
import pytest

from durable.reporting.inference import (
    ExperimentLogMissingError,
    deflated_sharpe_ratio,
    require_experiment_log,
    stationary_block_bootstrap,
)


def _sharpe(returns):
    if len(returns) < 2:
        return 0.0
    return float(np.mean(returns) / np.std(returns, ddof=1) * np.sqrt(12))


class TestStationaryBlockBootstrap:
    def test_not_iid(self):
        """Uses stationary block bootstrap, NOT IID — acceptance criterion.

        The block bootstrap uses avg_block_size > 1 by default (sqrt(T)),
        preserving time-series dependence structure. Verify that different
        block sizes produce different CIs (proving blocks matter).
        """
        np.random.seed(42)
        T = 60
        returns = np.random.normal(0.005, 0.03, T)

        # Default block size = sqrt(60) ≈ 7.7
        ci_default = stationary_block_bootstrap(returns, _sharpe, n_boot=5000, seed=42)

        # Very large blocks = sqrt(T)*3 — more conservative
        ci_large = stationary_block_bootstrap(
            returns, _sharpe, n_boot=5000, avg_block_size=20.0, seed=42
        )

        # Different block sizes produce different CIs
        default_width = ci_default.ci_high - ci_default.ci_low
        large_width = ci_large.ci_high - ci_large.ci_low
        assert default_width != pytest.approx(large_width, rel=0.01)

    def test_ci_nan_below_8_periods(self):
        """CI returns NaN below 8 periods — acceptance criterion."""
        returns = np.array([0.01, 0.02, -0.01, 0.03, 0.01])  # 5 periods
        result = stationary_block_bootstrap(returns, _sharpe)
        assert math.isnan(result.ci_low)
        assert math.isnan(result.ci_high)
        assert result.n_periods == 5

    def test_ci_valid_above_8_periods(self):
        """CI is valid with >= 8 periods."""
        np.random.seed(42)
        returns = np.random.normal(0.01, 0.03, 24)
        result = stationary_block_bootstrap(returns, _sharpe, n_boot=1000)
        assert not math.isnan(result.ci_low)
        assert not math.isnan(result.ci_high)
        assert result.ci_low < result.point_estimate < result.ci_high

    def test_identical_series_not_significant(self):
        """Identical series (zero returns) => significant=False."""
        returns = np.zeros(20)
        result = stationary_block_bootstrap(returns, np.mean, n_boot=1000)
        assert result.significant is False

    def test_strong_positive_significant(self):
        """Strongly positive returns are significant."""
        returns = np.array([0.05] * 30 + [0.04] * 30)
        result = stationary_block_bootstrap(returns, np.mean, n_boot=5000)
        assert result.significant is True


class TestDeflatedSharpeRatio:
    def test_dsr_decreases_with_trials(self):
        """DSR strictly decreases as n_trials rises — acceptance criterion."""
        dsr_1 = deflated_sharpe_ratio(sharpe=1.5, n_periods=60, n_trials=1)
        dsr_10 = deflated_sharpe_ratio(sharpe=1.5, n_periods=60, n_trials=10)
        dsr_100 = deflated_sharpe_ratio(sharpe=1.5, n_periods=60, n_trials=100)
        assert dsr_1 > dsr_10 > dsr_100

    def test_dsr_raises_on_missing_log(self, tmp_path):
        """DSR raises if experiment_log.csv is missing — acceptance criterion."""
        with pytest.raises(ExperimentLogMissingError):
            require_experiment_log(tmp_path / "nonexistent.csv")

    def test_dsr_reads_trial_count(self, tmp_path):
        """Reads n_trials from experiment log."""
        log = tmp_path / "experiment_log.csv"
        log.write_text("date,variant,sharpe\n2024-01-01,full,1.2\n2024-02-01,minus_mom,0.8\n")
        n = require_experiment_log(log)
        assert n == 2

    def test_dsr_in_0_1(self):
        """DSR is a probability in [0, 1]."""
        dsr = deflated_sharpe_ratio(sharpe=2.0, n_periods=120, n_trials=5)
        assert 0.0 <= dsr <= 1.0
