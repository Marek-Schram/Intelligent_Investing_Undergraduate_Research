---
name: factor-ic
description: Run information-coefficient analysis on a factor to test whether it is actually predictive - IC, IC decay, quantile monotonicity, and turnover. Use when the user asks whether a factor works, is predictive, or has signal.
---

# Factor IC analysis

Read `docs/09_ADVANCED_VALIDATION.md` §7. This answers a question the portfolio backtest cannot:
**is the factor itself predictive, or does the portfolio only look fine because of construction?**

A portfolio with equal weighting, sector caps, and a buffer rule can produce respectable
returns while every underlying factor has zero information content. IC is the direct test.

## Steps
1. Build the factor panel: `(date, ticker) -> factor_value`, point-in-time via the firewall.
2. Compute forward returns at multiple horizons: 1Q, 2Q, 4Q, 8Q.
3. **Spearman rank IC** per date (rank correlation of factor vs forward return). Rank, not
   Pearson — financial data has fat tails and outliers dominate a linear correlation.
4. Report: mean IC, IC std, **IC information ratio** (mean/std), t-stat, hit rate
   (fraction of periods with IC > 0).
5. **IC decay curve** across horizons. Where does the signal die? That determines the natural
   rebalance frequency — and if it dies inside one quarter, our quarterly cycle cannot capture it.
6. **Quantile analysis**: sort into 5 buckets, compute mean forward return per bucket.
   **Check monotonicity.** A factor whose quantiles are not monotonic is not a factor; it is
   noise with a threshold.
7. **Factor autocorrelation** — how much does the ranking change quarter to quarter? This is
   the turnover the factor implies before any buffer rule.
8. Sector-neutral variant: repeat within-sector to check the factor is not a sector bet.

## Interpretation guardrails
- |IC| of 0.02-0.05 is typical for a real equity factor. **|IC| > 0.15 on real data almost
  always means look-ahead** — run the backtest-validator subagent before believing it.
- IC t-stat < 2 means you cannot distinguish the factor from noise on this sample.
- Report the number of periods. 40 quarters is a small sample and the report must say so.
- Non-monotonic quantiles with a good top-minus-bottom spread means you have a tail effect,
  not a factor. Say that explicitly.

## Mandatory
- Log the run to experiment_log.csv — an IC test is a trial and counts toward Deflated Sharpe.
- Report IC alongside portfolio returns in every performance report.
