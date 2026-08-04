# 03 — Backtest Protocol (Anti-Overfitting Contract)

Extended by `docs/09` (CPCV, PBO, IC). A backtest is a claim: *"with only the information
available at the time, this is what would have happened."* Everything here keeps that honest.

## 1. Look-ahead prevention
`available_at = filing acceptance + 1 trading day`. The extra day reflects that you cannot
parse, score, and trade on a filing accepted at 16:31 ET.

**Four enforcement layers:**
1. `data/sec.py` attaches `available_at` at ingestion; rows without it are rejected.
2. Every query goes through `store.as_of(T)`.
3. **`firewall.py` asserts independently** — catching paths that bypass the store.
4. `tests/test_no_lookahead.py` corrupts a future filing and asserts earlier scores are
   unchanged. **If that test passes without the guard, the guard isn't real.**

Lagged disclosures use filing dates. Restatements: always the originally-filed figure.
**Prices: raw OHLCV only** — adjusted series are retroactively restated.

**LLM contamination:** a model trained after the test window has read the future. Run the
alpha-decay test (docs/10, TICKET-045); mark affected results CONTAMINATED and report separately.

## 2. Survivorship
The universe at `T` includes every eligible company listed on `T`, **including those that later
went bankrupt, were acquired, or delisted.** Tests must assert: 2008-01-01 contains LEH, WM,
BSC · 2000-01-01 contains >= 300 tickers not listed today · universe size NOT monotonically
increasing · delisting returns applied (acquisition => deal price; bankruptcy => −100% unless a
documented recovery). A missing delisting return silently deletes a loss from the record.

## 3. Train / validate / test
| Segment | Period | Permitted |
|---|---|---|
| Design | 1998-2010 | Look freely. Tune. Iterate. |
| Validation | 2011-2018 | Limited passes — log every one. |
| Holdout | 2019-present | **Touch at most twice, ever.** |

Log every run in `reports/experiment_log.csv`: date, hypothesis, preregistration status,
parameters, seed, result. **If you don't count your trials, you cannot know whether your result
is luck.** Walk-forward is the default; CPCV supplements it.

## 4. Cost model (conservative)
Commission $0 · spread `max(0.02%, 0.5 × median_60d_spread)` each way · slippage 0.10% for
ADV >= $50M, 0.25% for $10-50M · **Almgren-Chriss market impact** (temporary square-root +
permanent linear, `backtest/impact.py`) · delisting friction 1.0% · taxes modeled in
`tax/after_tax.py`.

Report at 1x, 2x, 3x. **If the edge disappears at 2x, it was never an edge.**

## 4.1 Accounting invariants (added v1.3)

Any backtest that violates one of these is invalid, not merely inaccurate:

1. **Cash is never negative.** Not at any point in any period. Negative cash is unmodelled
   leverage. Enforce via sequenced execution (docs/01), not via a post-hoc buffer — a buffer was
   tested and made the problem *worse*.
2. **Positions + cash reconcile to NAV** every period to within 1e-6.
3. **Every share sold was held.** No implicit shorting through a sizing bug.
4. **Projected turnover is checked before trading**, not just reported after (SPEC §7.2).

## 5. Required outputs
Equity curve vs SPY/VTI/equal-weight · CAGR, vol, Sharpe, Sortino, max DD + duration, Calmar,
turnover · rolling 3-year excess · worst 10 drawdowns with holdings · **nine-variant ablation
table** · FF5+MOM alpha, t-stat, loadings · Deflated Sharpe · **CPCV distribution and PBO** ·
**factor IC table** · **after-tax alongside pre-tax** · per-decade breakdown.

## 6. Statistical honesty
**Deflated Sharpe** using the logged trial count · **minimum track record length** · **PBO**
(docs/09) · **factor IC** — a portfolio can look fine while every factor has zero information
content · **parameter sensitivity** ±30%, prefer plateaus over peaks · **sub-period stability**
per decade (one credible large-cap US F-Score backtest 1997-2024 returned 6.1%/yr vs 9.4% for
SPY, with value coming from *avoiding* the worst names, while international evidence 2000-2018
finds ~10%/yr high-minus-low — both can be true; expect regime dependence and say so) ·
**randomization test** against 100 random 20-stock portfolios from the same universe.

## 7. Kill criteria (decided in advance)
1. Live results deviate > 2 sd of quarterly tracking error from backtest expectations
2. FF5+MOM alpha indistinguishable from zero (|t| < 2)
3. Deflated Sharpe < 0
4. Realized turnover > 60%/yr — **and note this fires on the un-amended spec.** The
   simulation that produced these amendments measured **99.6%/yr** with buffer rank 60 and no
   no-trade band. Turnover must be controlled by design (SPEC §7.1, §7.2), not merely measured.
5. You cannot explain, from the memo, why each holding is there
6. **PBO > 0.50**

Evaluated automatically on every report. Write these down now, with no money at stake.

## 8. The most likely honest outcome
The base rate for retail systematic equity strategies beating a low-cost index after costs and
taxes is low. A plausible good outcome is **matching the index with a portfolio you deeply
understand, while building transferable quant skills.** Name it, so a mediocre backtest doesn't
get tortured into a fake good one.
