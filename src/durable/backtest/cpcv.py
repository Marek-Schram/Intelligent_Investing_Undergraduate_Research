"""Combinatorial Purged CV and PBO. TICKET-030.

docs/09. Walk-forward gives ONE out-of-sample curve. CPCV runs all C(10,3)=120 combinations
and returns a DISTRIBUTION, so you can ask: in what fraction of possible histories did this work?

make_groups(periods, n_groups=10) -> contiguous partitions. Contiguity is essential.
purge(train_idx, test_idx, horizon=4) -> remove train samples whose label horizon overlaps test.
embargo(train_idx, test_idx, n_periods, pct=0.01) -> buffer after each test group.
run_cpcv(scores_by_date, prices, ...) -> list[CPCVPath]. Cache scores by (as_of, snapshot_id):
    one scoring pass, 120 cheap evaluations, not 120 full backtests.
probability_of_backtest_overfitting(paths) -> float. >0.50 = more likely overfit than genuine.
    Kill criterion #6. NEVER tune parameters to improve it -- that is overfitting the
    overfitting test.
summarize(paths, walk_forward_sharpe) -> also reports WHERE the walk-forward result lands in
    the distribution. Top decile => the walk-forward result was luck. Say so.

Data source: factor scores, prices from PIT store.
available_at logic: all data filtered via store.as_of(as_of) upstream.
Spec section: docs/09.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np


@dataclass(frozen=True)
class CPCVPath:
    """One CPCV path result."""

    test_groups: tuple[int, ...]
    sharpe: float
    returns: np.ndarray


@dataclass(frozen=True)
class CPCVSummary:
    """Summary statistics of all CPCV paths."""

    n_paths: int
    mean_sharpe: float
    median_sharpe: float
    stdev_sharpe: float
    percentile_5: float
    fraction_beating_benchmark: float
    pbo: float
    walk_forward_percentile: float | None
    seed: int


def make_groups(n_periods: int, n_groups: int = 10) -> list[np.ndarray]:
    """Split periods into n_groups contiguous partitions."""
    indices = np.arange(n_periods)
    return [arr for arr in np.array_split(indices, n_groups)]


def purge(
    train_idx: np.ndarray,
    test_idx: np.ndarray,
    horizon: int = 4,
) -> np.ndarray:
    """Remove train samples whose label horizon overlaps with test set.

    If a train sample at index i has a label that looks ahead `horizon` periods,
    and any of i..i+horizon-1 falls in test, that train sample is purged.
    """
    test_set = set(test_idx)
    purged = []
    for i in train_idx:
        overlap = any(i + h in test_set for h in range(horizon))
        if not overlap:
            purged.append(i)
    return np.array(purged, dtype=int)


def embargo_indices(
    train_idx: np.ndarray,
    test_idx: np.ndarray,
    n_periods: int,
    pct: float = 0.01,
) -> np.ndarray:
    """Apply embargo buffer after each test group boundary.

    Embargo size = max(1 quarter equivalent, pct * n_periods).
    """
    embargo_size = max(n_periods // 40, int(pct * n_periods))
    embargo_size = max(embargo_size, 1)

    embargo_set = set()
    for t in test_idx:
        for e in range(1, embargo_size + 1):
            embargo_set.add(t + e)

    return np.array(
        [i for i in train_idx if i not in embargo_set],
        dtype=int,
    )


def _compute_sharpe(returns: np.ndarray) -> float:
    """Annualized Sharpe from period returns."""
    if len(returns) < 2 or np.std(returns, ddof=1) == 0:
        return 0.0
    return float(np.mean(returns) / np.std(returns, ddof=1) * np.sqrt(12))


def generate_paths(n_groups: int = 10, k: int = 3) -> list[tuple[int, ...]]:
    """Generate all C(n,k) test-group combinations."""
    return list(combinations(range(n_groups), k))


def run_cpcv(
    period_returns: np.ndarray,
    n_groups: int = 10,
    k: int = 3,
    horizon: int = 4,
    embargo_pct: float = 0.01,
    seed: int = 42,
) -> list[CPCVPath]:
    """Run all CPCV paths. Returns Sharpe for each test combination.

    This evaluates strategy returns on each C(n,k) held-out combination,
    with purging and embargo applied to prevent leakage.
    """
    n_periods = len(period_returns)
    groups = make_groups(n_periods, n_groups)

    paths = []
    for test_group_indices in generate_paths(n_groups, k):
        test_idx = np.concatenate([groups[g] for g in test_group_indices])
        train_groups = [g for g in range(n_groups) if g not in test_group_indices]
        train_idx = np.concatenate([groups[g] for g in train_groups])

        train_idx = purge(train_idx, test_idx, horizon)
        train_idx = embargo_indices(train_idx, test_idx, n_periods, embargo_pct)

        test_returns = period_returns[test_idx]
        sharpe = _compute_sharpe(test_returns)

        paths.append(
            CPCVPath(
                test_groups=test_group_indices,
                sharpe=sharpe,
                returns=test_returns,
            )
        )

    return paths


def probability_of_backtest_overfitting(paths: list[CPCVPath]) -> float:
    """PBO = fraction of paths with Sharpe <= 0.

    >0.50 means more likely overfit than genuine. Kill criterion #6.
    """
    if not paths:
        return 1.0
    n_negative = sum(1 for p in paths if p.sharpe <= 0)
    return n_negative / len(paths)


def summarize(
    paths: list[CPCVPath],
    walk_forward_sharpe: float | None = None,
    seed: int = 42,
) -> CPCVSummary:
    """Summarize CPCV distribution and locate walk-forward result's percentile."""
    sharpes = np.array([p.sharpe for p in paths])

    if len(sharpes) == 0:
        return CPCVSummary(
            n_paths=0,
            mean_sharpe=0.0,
            median_sharpe=0.0,
            stdev_sharpe=0.0,
            percentile_5=0.0,
            fraction_beating_benchmark=0.0,
            pbo=1.0,
            walk_forward_percentile=None,
            seed=seed,
        )

    pbo = probability_of_backtest_overfitting(paths)

    wf_percentile = None
    if walk_forward_sharpe is not None:
        wf_percentile = float(np.mean(sharpes <= walk_forward_sharpe) * 100)

    return CPCVSummary(
        n_paths=len(paths),
        mean_sharpe=float(np.mean(sharpes)),
        median_sharpe=float(np.median(sharpes)),
        stdev_sharpe=float(np.std(sharpes, ddof=1)) if len(sharpes) > 1 else 0.0,
        percentile_5=float(np.percentile(sharpes, 5)),
        fraction_beating_benchmark=float(np.mean(sharpes > 0)),
        pbo=pbo,
        walk_forward_percentile=wf_percentile,
        seed=seed,
    )
