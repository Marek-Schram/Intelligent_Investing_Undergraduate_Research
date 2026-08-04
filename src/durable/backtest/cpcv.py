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
"""

from __future__ import annotations
