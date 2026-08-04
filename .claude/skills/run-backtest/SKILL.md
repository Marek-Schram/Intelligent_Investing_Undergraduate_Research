---
name: run-backtest
description: Run the walk-forward backtest and CPCV validation under the full protocol. Use when the user asks to backtest, test historically, or evaluate performance.
---

# Backtest procedure

Read `docs/03_BACKTEST_PROTOCOL.md` and `docs/09_ADVANCED_VALIDATION.md` first.

## Pre-flight
1. Segment: design (1998-2010) / validation (2011-2018) / holdout (2019+).
   **Holdout => warn and require explicit confirmation.**
2. `tests/test_no_lookahead.py`, `test_universe_integrity.py`, `test_firewall.py` pass.
3. Record snapshot_id, seed. Was this preregistered?
4. **If any LLM feature is enabled, check the model's training cutoff against the window.**
   Overlap => results are CONTAMINATED and reported separately.
5. **Run IC analysis on each factor first.** If a factor has no IC, the portfolio result is
   construction, not signal, and the backtest will mislead you about why it worked.

## Run
6. Walk-forward loop. No parameter fitted on data after the date it is applied.
7. Costs at 1x, 2x, 3x — including Almgren-Chriss market impact.
8. Full ablation set (SPEC §10, nine variants).
9. **CPCV N=10, k=3 (120 paths).** Cache scores by (as_of, snapshot_id).

## Report — always
Equity curve vs SPY/VTI/equal-weight · CAGR, vol, Sharpe, Sortino, max DD + duration, Calmar,
turnover · **CPCV distribution: mean/median/stdev path Sharpe, 5th percentile, fraction beating
benchmark** · **PBO** (>0.50 = likely overfit) · rolling 3-year excess · ablation table ·
FF5+MOM alpha, t-stat, loadings · Deflated Sharpe · **factor IC table** · after-tax alongside
pre-tax · per-decade breakdown.

## Mandatory afterward
10. Append to `reports/experiment_log.csv` — seed, segment, preregistration status, LLM
    model/prompt version. Never skip.
11. Excess CAGR > 8%/yr => suspected bug. Invoke backtest-validator before reporting it.
12. State the honest conclusion FIRST, including whether alpha survives factor adjustment and
    what PBO says.
