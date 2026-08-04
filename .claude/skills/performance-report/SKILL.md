---
name: performance-report
description: Generate an automated performance report - weekly pulse, quarterly review, research bulletin, event report, or annual assessment.
---

# Performance report

Read `docs/07_PERFORMANCE_REPORTING.md`. Pure functions of committed data; no network.

**Type:** pulse | quarterly | research | event | annual. Ambiguous => quarterly.

**Pin:** snapshot_id, git commit, config hash, seeds, trial count, LLM model/prompt versions.

## Compute, in order
1. TWR (chain-linked) AND MWR (IRR). The gap is itself a finding.
2. Risk: CAGR, vol, Sharpe, Sortino, Calmar, max DD + duration, skew, kurtosis, up/down capture.
3. **Stationary block bootstrap** CIs — not IID; squared returns are persistent.
4. Ledoit-Wolf robust test for the Sharpe DIFFERENCE. Different only if zero is outside the CI.
5. Minimum track record length · Deflated Sharpe · **PBO from the latest CPCV run**.
6. Brinson attribution — report the interaction term.
7. FF5+MOM with Newey-West. Alpha, t-stat, loadings, residual.
8. Per-position contribution sorted by absolute contribution.
9. **Factor IC table** — IC, IR, t-stat, decay per factor.
10. Tax: realized ST/LT, harvested losses, carryforward, tax alpha vs naive-FIFO, wash-sale
    disallowances, after-tax return.
11. Process health: turnover, tracking error, holding period, fill quality, reconcile status,
    override count, extraction audit error rate, **firewall violations (should be zero)**.
12. Kill criteria — all six, PASS/WARN/FAIL.
13. Sleeve E separately, with hit rate and exclusion count.

## Narrative — enforced
Lead with the benchmark · never "outperformed" without the CI adjacent · never call an
insignificant result skill · name largest positive AND negative contributor by ticker · state
one thing that went wrong · no forward-looking language.

## Hard rules
Small-sample banner until 12 quarters · N < 8 prints "(CI unavailable)" · show since-inception,
YTD, AND trailing 12m · NEVER submit or modify orders · unusually good result => say so and
recommend backtest-validator before it enters the paper.
