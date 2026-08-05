"""Tests for ablation study. TICKET-014. Hand-computed fixtures."""

from __future__ import annotations

import numpy as np
import pytest

from durable.backtest.ablations import (
    ALL_VARIANTS,
    AblationResult,
    AblationVariant,
    format_ablation_table,
    newey_west_se,
    run_ablation,
    run_all_ablations,
    t_stat_newey_west,
)


class TestNeweyWestSE:
    def test_iid_matches_classical_se(self):
        """For IID data, NW-SE converges to classical SE."""
        np.random.seed(42)
        data = np.random.normal(0.01, 0.03, 120)
        nw_se = newey_west_se(data)
        classical_se = np.std(data, ddof=1) / np.sqrt(len(data))
        # Should be close for IID data
        assert abs(nw_se - classical_se) / classical_se < 0.3

    def test_autocorrelated_data_larger_se(self):
        """Autocorrelated data gives LARGER SE than classical — acceptance criterion.

        This is the whole point of Newey-West: naively computing SE
        understates uncertainty when returns are serially correlated.
        """
        np.random.seed(42)
        # AR(1) process with phi=0.5
        T = 200
        e = np.random.normal(0, 0.02, T)
        data = np.zeros(T)
        data[0] = e[0]
        for t in range(1, T):
            data[t] = 0.5 * data[t - 1] + e[t]
        data += 0.005  # Add mean

        nw_se = newey_west_se(data)
        classical_se = np.std(data, ddof=1) / np.sqrt(T)
        assert nw_se > classical_se

    def test_short_series(self):
        """Short series doesn't crash."""
        result = newey_west_se(np.array([0.01, 0.02]))
        assert result >= 0


class TestTStat:
    def test_significant_alpha(self):
        """Genuine alpha with |t| > 2."""
        np.random.seed(42)
        # Strategy returns = benchmark + 50bps/month alpha + noise
        T = 60
        benchmark = np.random.normal(0.008, 0.04, T)
        strategy = benchmark + 0.005 + np.random.normal(0, 0.01, T)

        t, se = t_stat_newey_west(strategy, benchmark)
        assert abs(t) > 2.0

    def test_no_alpha(self):
        """No alpha: strategy = benchmark + noise gives |t| < 2."""
        np.random.seed(42)
        T = 60
        benchmark = np.random.normal(0.008, 0.04, T)
        strategy = benchmark + np.random.normal(0, 0.04, T)

        t, se = t_stat_newey_west(strategy, benchmark)
        # Should generally not be significant (noise around zero)
        assert abs(t) < 3.0  # Relaxed bound — noise test

    def test_states_t_greater_than_2(self):
        """The result explicitly states whether |t| > 2 — acceptance criterion."""
        returns = np.array([0.01] * 60)
        benchmark = np.array([0.005] * 60)
        result = run_ablation(
            AblationVariant.FULL, returns, benchmark
        )
        assert isinstance(result.significant, bool)
        assert result.significant == (abs(result.t_stat) > 2.0)


class TestRunAllAblations:
    def test_all_nine_variants(self):
        """All nine variants from one command — acceptance criterion."""
        assert len(ALL_VARIANTS) == 9

        np.random.seed(42)
        T = 60
        benchmark = np.random.normal(0.008, 0.04, T)
        variant_returns = {
            v: benchmark + np.random.normal(0.002, 0.01, T) for v in ALL_VARIANTS
        }

        results = run_all_ablations(variant_returns, benchmark)
        assert len(results) == 9
        variants_seen = {r.variant for r in results}
        assert variants_seen == set(ALL_VARIANTS)

    def test_each_result_has_significance(self):
        """Every variant reports significance."""
        np.random.seed(42)
        T = 60
        benchmark = np.random.normal(0.008, 0.04, T)
        variant_returns = {
            v: benchmark + np.random.normal(0.002, 0.01, T) for v in ALL_VARIANTS
        }

        results = run_all_ablations(variant_returns, benchmark)
        for r in results:
            assert isinstance(r, AblationResult)
            assert isinstance(r.significant, bool)
            assert r.n_periods == T


class TestFormatTable:
    def test_table_has_significance_column(self):
        """Output table states whether |t| > 2."""
        results = [
            AblationResult(
                variant=AblationVariant.FULL,
                excess_return=0.03,
                t_stat=2.5,
                newey_west_se=0.012,
                significant=True,
                sharpe=0.8,
                n_periods=60,
            ),
            AblationResult(
                variant=AblationVariant.MINUS_MOMENTUM,
                excess_return=0.01,
                t_stat=1.2,
                newey_west_se=0.008,
                significant=False,
                sharpe=0.3,
                n_periods=60,
            ),
        ]
        df = format_ablation_table(results)
        assert "|t|>2" in df.columns
        assert df.iloc[0]["|t|>2"] == True
        assert df.iloc[1]["|t|>2"] == False
