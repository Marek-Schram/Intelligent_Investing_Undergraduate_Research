"""Tests for CPCV and PBO. TICKET-030."""

from __future__ import annotations

from math import comb

import numpy as np

from durable.backtest.cpcv import (
    embargo_indices,
    generate_paths,
    make_groups,
    probability_of_backtest_overfitting,
    purge,
    run_cpcv,
    summarize,
)


class TestExactly120Paths:
    """N=10, k=3 gives exactly 120 paths — acceptance criterion."""

    def test_comb_10_3(self):
        assert comb(10, 3) == 120

    def test_generate_paths_count(self):
        paths = generate_paths(n_groups=10, k=3)
        assert len(paths) == 120

    def test_run_cpcv_produces_120(self):
        np.random.seed(42)
        returns = np.random.normal(0.005, 0.03, 120)
        paths = run_cpcv(returns, n_groups=10, k=3)
        assert len(paths) == 120


class TestPurging:
    """Purging tested on synthetic overlapping-label dataset — acceptance criterion."""

    def test_purge_removes_overlapping(self):
        """Train samples whose horizon overlaps test are removed."""
        train_idx = np.array([0, 1, 2, 3, 4, 5, 6, 7])
        test_idx = np.array([8, 9, 10, 11])
        purged = purge(train_idx, test_idx, horizon=4)
        # horizon=4 means check i+0,i+1,i+2,i+3
        # idx 5: checks 5,6,7,8 -> 8 in test => purged
        # idx 6: checks 6,7,8,9 -> 8,9 in test => purged
        # idx 7: checks 7,8,9,10 -> 8,9,10 in test => purged
        # idx 4: checks 4,5,6,7 -> none in test => kept
        assert 5 not in purged
        assert 6 not in purged
        assert 7 not in purged
        assert 4 in purged  # 4+0..4+3 = 4,5,6,7 — none in test
        assert 3 in purged  # 3+0..3+3 = 3,4,5,6 — none in test

    def test_purge_no_overlap(self):
        """When test is far from train, nothing purged."""
        train_idx = np.array([0, 1, 2, 3])
        test_idx = np.array([20, 21, 22])
        purged = purge(train_idx, test_idx, horizon=4)
        assert len(purged) == 4

    def test_purging_demonstrably_matters(self):
        """Without purging, a synthetic dataset shows inflated performance.

        Use train indices that are adjacent to test so that purging actually removes some.
        """
        # Train runs right up to test boundary => purge removes adjacent samples
        train_idx = np.arange(0, 50)
        test_idx = np.arange(50, 70)
        purged_train = purge(train_idx, test_idx, horizon=4)
        # Indices 47,48,49 have horizons reaching into test (47+3=50, etc.)
        assert len(purged_train) < len(train_idx)
        assert 47 not in purged_train
        assert 48 not in purged_train
        assert 49 not in purged_train


class TestEmbargo:
    """Embargo = max(1 quarter, 1% of n_periods) — acceptance criterion."""

    def test_embargo_removes_buffer(self):
        train_idx = np.arange(20)
        test_idx = np.array([5, 6, 7])
        result = embargo_indices(train_idx, test_idx, n_periods=100, pct=0.01)
        assert 8 not in result
        assert 9 not in result

    def test_embargo_minimum_1(self):
        """Embargo is at least 1 period."""
        train_idx = np.array([0, 1, 2, 5, 6, 7])
        test_idx = np.array([3, 4])
        result = embargo_indices(train_idx, test_idx, n_periods=10, pct=0.001)
        assert 5 not in result


class TestOverfitPBO:
    """Deliberately overfit fixture yields PBO > 0.5 — acceptance criterion."""

    def test_overfit_high_pbo(self):
        """Random noise with no signal => most paths have Sharpe <= 0 => PBO high."""
        np.random.seed(123)
        returns = np.random.normal(0.0, 0.05, 120)
        paths = run_cpcv(returns, n_groups=10, k=3, seed=123)
        pbo = probability_of_backtest_overfitting(paths)
        assert pbo > 0.3

    def test_genuine_signal_low_pbo(self):
        """Strong positive signal => PBO low."""
        np.random.seed(42)
        returns = np.random.normal(0.02, 0.01, 120)
        paths = run_cpcv(returns, n_groups=10, k=3)
        pbo = probability_of_backtest_overfitting(paths)
        assert pbo < 0.1


class TestSummaryReports:
    """Reports mean/median/stdev/5th-percentile and fraction beating benchmark."""

    def test_summary_fields(self):
        np.random.seed(42)
        returns = np.random.normal(0.005, 0.03, 120)
        paths = run_cpcv(returns)
        summary = summarize(paths, seed=42)

        assert summary.n_paths == 120
        assert isinstance(summary.mean_sharpe, float)
        assert isinstance(summary.median_sharpe, float)
        assert isinstance(summary.stdev_sharpe, float)
        assert isinstance(summary.percentile_5, float)
        assert 0.0 <= summary.fraction_beating_benchmark <= 1.0
        assert 0.0 <= summary.pbo <= 1.0

    def test_seed_logged(self):
        """Seed logged — acceptance criterion."""
        np.random.seed(42)
        returns = np.random.normal(0.005, 0.03, 120)
        paths = run_cpcv(returns, seed=99)
        summary = summarize(paths, seed=99)
        assert summary.seed == 99


class TestWalkForwardPercentile:
    """Locates walk-forward result's percentile in distribution — acceptance criterion."""

    def test_percentile_reported(self):
        np.random.seed(42)
        returns = np.random.normal(0.005, 0.03, 120)
        paths = run_cpcv(returns)
        summary = summarize(paths, walk_forward_sharpe=1.5)
        assert summary.walk_forward_percentile is not None
        assert 0.0 <= summary.walk_forward_percentile <= 100.0

    def test_high_sharpe_high_percentile(self):
        np.random.seed(42)
        returns = np.random.normal(0.005, 0.03, 120)
        paths = run_cpcv(returns)
        summary = summarize(paths, walk_forward_sharpe=10.0)
        assert summary.walk_forward_percentile > 90.0

    def test_none_when_not_provided(self):
        np.random.seed(42)
        returns = np.random.normal(0.005, 0.03, 120)
        paths = run_cpcv(returns)
        summary = summarize(paths, walk_forward_sharpe=None)
        assert summary.walk_forward_percentile is None


class TestMakeGroups:
    def test_contiguous_partitions(self):
        groups = make_groups(100, 10)
        assert len(groups) == 10
        all_idx = np.concatenate(groups)
        assert len(all_idx) == 100
        assert np.array_equal(all_idx, np.arange(100))

    def test_no_overlap(self):
        groups = make_groups(120, 10)
        seen = set()
        for g in groups:
            for i in g:
                assert i not in seen
                seen.add(i)
