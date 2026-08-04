# 09 — Advanced Validation (CPCV, PBO, IC, and the Two Laws)

The most important document here. Everything else finds signal; this is how you know whether you
found any.

## 0. Plain-English
The backtest gives **one answer** — one particular way of slicing history into practice-rounds
and test-rounds. Slice it differently and you get a different answer. CPCV runs **every possible
slicing** and gives a distribution, so you can ask: *"in what fraction of possible histories did
this make money?"* Under half means you found a coincidence — and now you have a number proving it.

Separately, IC asks a question the portfolio backtest cannot: **is the signal itself any good,
or does the portfolio only look fine because of how it's built?**

## 1. Why walk-forward alone isn't enough
Walk-forward produces **one** out-of-sample curve, from one chunking of history in one order.
Start six months later, or use 9-month chunks, and you get a different curve — some great, some
terrible. The strategy gets deployed or killed on whichever you happened to run. López de Prado
calls this **backtest selection bias**.

Standard k-fold doesn't help: it assumes independent observations, but financial series have
serial correlation, regime changes, and label leakage.

## 2. The three mechanisms
**Purging** — remove training samples whose label horizon overlaps the test set:
`remove train where t ∈ [t_start − h, t_start)`.
**Embargo** — a buffer after each test group, typically **1-2% of dataset length**, because
serial correlation extends past the purge zone.
**Combinatorial paths** — partition into `N` groups, test all `C(N,k)` combinations.

| Config | Paths | Test fraction |
|---|---|---|
| N=6, k=2 | 15 | 33% |
| N=8, k=2 | 28 | 25% |
| **N=10, k=3** | **120** | **30%** |
| N=12, k=4 | 495 | 33% |

**Ours: N=10, k=3 → 120 paths.** With ~112 quarterly rebalances, each group is ~11 quarters —
enough to contain a real market regime.

## 3. PBO
$$PBO = \\frac{\\#\\text{paths with negative OOS performance}}{\\text{total paths}}$$

**PBO > 0.50 means more likely overfit than genuine.** Kill criterion #6, on every report.

Report alongside: mean and median path Sharpe · standard deviation (path dependence) · **5th
percentile path** (realistic bad case) · fraction beating the *benchmark*, not just zero · and
**where the walk-forward result lands in the distribution** (top decile => it was luck).

## 4. The Two Laws
> **First Law:** Focus research effort on *theories*, not on backtesting trading rules.
> **Second Law:** Never run a backtest until your model is fully specified. *"Backtesting while
> researching is like drinking and driving. Do not research under the influence of a backtest."*

This is why `docs/00` exists and must change *before* the code. The spec is the theory; the
backtest only validates it. It is also why **automated factor mining is disqualifying** — see
docs/13 §3.

## 5. Deliberately not adopted
| Technique | Why not |
|---|---|
| Triple-barrier labeling | For path-dependent entry/exit with stops. We hold for years. |
| Meta-labeling | Needs a primary ML model producing many signals. We have ~20 positions and a rule. |
| Fractional differentiation | Solves stationarity for ML features. Ours are accounting ratios. |
| Sequential bootstrap | For heavy label overlap at high frequency. Quarterly + embargo suffices. |

Revisit all four only if an ML component ever appears.

## 6. Implementation notes
CPCV is expensive: 120 paths × the scoring pipeline. **Cache scores by `(as_of, snapshot_id)`** —
scores don't change per path, only the partition does. That turns 120 backtests into one scoring
pass and 120 cheap evaluations. Embargo `= max(1 quarter, 0.01 × n_periods)`; purge horizon
`h` = max holding period used in any fit (4 quarters). Report CPCV **alongside** walk-forward,
never instead — walk-forward is what live trading looks like; CPCV judges whether it got lucky.

## 7. Factor IC — validating the signal, not the portfolio
Added after the open-source audit (docs/13 §2.3) revealed a genuine hole: our validation tested
*portfolios*, never *factors*.

**Why they differ.** Equal weighting, sector caps, and the top-60 buffer are themselves a
strategy. A portfolio built on a factor with zero information content can still produce
respectable returns from construction alone. The randomization test in `docs/03 §6` was designed
to catch that; IC measures it directly.

**What to compute** (`factors/ic.py`, TICKET-043):
- **Spearman rank IC** per date — rank, not Pearson; fat tails make linear correlation dominated
  by outliers
- Mean IC, std, **information ratio** (mean/std), t-stat, hit rate
- **IC decay** across 1/2/4/8-quarter horizons — where the signal dies determines the natural
  rebalance frequency. **If it dies inside a quarter, our cycle structurally cannot capture it**,
  which is a reason to drop the factor, not to trade more often.
- **Quantile monotonicity** — a factor whose quantiles aren't monotonic is not a factor; it is
  noise with a threshold. Non-monotonic with a big top-minus-bottom spread means a tail effect.
- **Factor autocorrelation** — the turnover implied before any buffer rule
- **Sector-neutral IC** — if raw IC is strong but sector-neutral IC is near zero, it's a sector bet

**Guardrails.** |IC| of 0.02-0.05 is typical for a real equity factor. **|IC| > 0.15 on real
data almost always means look-ahead** — run the backtest-validator before believing it. t-stat
< 2 means indistinguishable from noise on this sample. Always report n_periods.

An IC test is a **trial** and counts toward the Deflated Sharpe trial count. Log it.
