---
name: validate-strategy
description: Run combinatorial purged cross-validation and compute the probability of backtest overfitting. Use when the user asks whether a strategy is real, robust, overfit, or statistically trustworthy.
---

# CPCV validation

Read `docs/09_ADVANCED_VALIDATION.md`.

Walk-forward gives ONE out-of-sample curve from one way of slicing history. Slice differently
and you get a different answer. CPCV gives a distribution across all slicings, so you can ask:
**in what fraction of possible histories did this work?**

## Steps
1. Confirm the model is FULLY SPECIFIED. Per the Second Law, never run this while still
   iterating. If the user is still tuning, say so and stop.
2. Partition into N=10 contiguous groups; test all C(10,3) = 120 combinations.
3. **Purge**: remove training samples whose label horizon overlaps the test set (horizon = max
   holding period used in any fit; 4 quarters here).
4. **Embargo**: max(1 quarter, 1% of n_periods) after each test group.
5. Evaluate each path. Cache scores by (as_of, snapshot_id) — one scoring pass, 120 cheap evals.

## Report
- **PBO** = paths with negative OOS / total. **> 0.50 => likely overfit.**
- Mean, median, stdev of path Sharpe · 5th percentile path (realistic bad case)
- Fraction of paths beating the benchmark, not just beating zero
- Histogram of path Sharpes
- **Where the single walk-forward result lands in the distribution.** Top decile => the
  walk-forward result was luck. Say so plainly.

## Hard rules
- Report CPCV ALONGSIDE walk-forward, never instead.
- PBO is kill criterion #6.
- **Never tune parameters to improve PBO.** That is overfitting the overfitting test.
- Log the run, seed, and path count.
