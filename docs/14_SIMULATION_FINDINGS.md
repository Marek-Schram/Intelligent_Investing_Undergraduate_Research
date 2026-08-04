# 14 — Simulation Findings (v1.3 amendments)

What happened when the spec was actually run end-to-end, what broke, and what changed as a
result. This is a research artifact: the failures are the interesting part.

---

## 0. Plain-English version

Before writing the real system, I built a working toy version of it and ran it on 16 years of
made-up-but-realistic market data — 300 companies, quarterly rebalances, real filing delays,
companies that go bankrupt, the works.

**Two things broke that nobody would have caught by reading the documents.**

First, the portfolio kept spending money it didn't have. Not because of a coding mistake — the
design itself never accounted for the fact that trading *costs money*, and that money has to
come from somewhere. In a real brokerage account, roughly one quarter in five would have been
a rejected order or an accidental margin loan.

Second, the strategy traded about **100% of itself every year** — meaning it effectively
replaced its entire portfolio annually. The plan explicitly says to abandon the strategy if
that number goes above 60%. So the strategy, as designed, failed its own quit-rule immediately.
Nobody noticed because the documents described *measuring* turnover but never described
*controlling* it.

Both are now fixed, and the fixes are tested.

---

## 1. Method

A minimal but faithful implementation of SPEC §1–8: point-in-time fundamentals with filing lags
and restatements, raw OHLCV with splits, delistings including bankruptcies, the durability and
valuation scores, momentum, buffer-zone selection, position and sector caps, and sell rules.

- 300 synthetic companies, 2010–2026, 28 delistings (bankruptcies and acquisitions)
- 19,411 fundamental records with realistic 25–75 day filing lags, 567 restatements
- 54 quarterly rebalances, 2013-02 → 2026-06
- Restatements deliberately excluded from scoring (originally-filed values only)

The point was never to measure returns — synthetic data cannot tell you that. It was to find
out whether **the machinery works**.

---

## 2. Finding 1 — Negative cash in 11 of 54 quarters

### What happened
The account went cash-negative in 20% of rebalances. Small amounts (~$100–850 on a $240k
portfolio), but the sign is what matters: that is unmodelled leverage, and a real broker either
rejects the order or quietly extends margin.

### Root cause
Not a coding bug — a **design omission**. The spec says compute `target = NAV × weight` and
trade to it. Transaction costs are then paid *from cash* but were never budgeted *into* the
target. When fully invested, the account ends each rebalance short by roughly the cost amount.

### The obvious fix does not work
A cash buffer was the natural first idea. It was tested and **made things worse**:

| Cash buffer | Negative-cash quarters |
|---|---|
| 0.0% | 11 |
| 0.5% | 4 |
| 1.0% | 4 |
| 1.5% | **7** |
| 2.0% | **8** |

Larger buffers reserve more cash but shrink the invested base, which enlarges the catch-up
trade next quarter and generates more cost. **This is why the fix had to be architectural.**

### The fix — sequenced execution
1. Sells execute first; proceeds recorded net of cost.
2. `affordable = cash / (1 + cost_rate)` — cost reserved on the buy side.
3. Buys exceeding affordable cash scale **pro-rata**, and the shortfall is logged.

Pro-rata rather than priority-ordered is deliberate: funding top-ranked names first would
concentrate the portfolio precisely in tight-cash quarters — a risk change disguised as an
execution detail.

**Result: 11 → 0 negative quarters. Cost: 0.06pp/yr in CAGR.** Three quarters hit a funding
shortfall and were correctly scaled down rather than borrowing.

*Implemented: `docs/01` execution sequencing · TICKET-047 · `tests/test_sequencing.py` ·
config `sequenced_execution: true` · guarded by a PreToolUse hook.*

---

## 3. Finding 2 — 99.6% annualized turnover: the strategy failed its own kill criterion

### What happened
Kill criterion #4 says abandon the strategy above 60%/yr turnover. Measured: **99.6%**.

### Decomposition — the surprising part
| Source | Annualized |
|---|---|
| Name changes (entries/exits) | 62.4pp |
| **Drift back to equal weight** | **37.2pp** |

**37% of all turnover came from rebalancing continuing holdings back to equal weight** — before
a single name changed. The spec says "equal weight, then apply constraints and renormalize"
every quarter, which mandates trading a position that has merely drifted from 5.0% to 5.4%.

### Root cause
The spec **measured** turnover but never **controlled** it. A kill criterion with no control
mechanism is a post-mortem, not a control.

### The fix — two mechanisms
**a) No-trade band (3% of NAV).** Continuing holdings trade only when drift exceeds the band.
Name changes and constraint breaches always execute. Drift turnover: **37.2pp → ~7pp.**

**b) Buffer rank 60 → 80.** Measured sensitivity:

| Buffer rank | Turnover | CAGR |
|---|---|---|
| 55 | 70.9% | 7.36% |
| 70 | 50.9% | 6.62% |
| **80** | **35.7%** | 8.59% |
| 90 | 27.8% | 6.58% |
| 105 | 21.9% | 8.13% |

**The turnover column is monotonic. The CAGR column is not.**

That distinction is the whole point. Turnover falling with buffer width is a structural
mechanism — wider buffer, fewer forced exits, less trading. The CAGR column jumps around
(7.36 / 6.62 / 8.59 / 6.58 / 8.13) with no pattern: **that is noise.**

So rank 80 is chosen **on the turnover constraint**, and **no return improvement is claimed**.
The 8.59% at rank 80 is luck, and a test exists specifically to stop a future reader from
quoting it as a benefit. This is PROTOCOL §6's plateau-versus-peak rule applied honestly to our
own change.

**Result: 99.6% → 35.7% turnover. Kill criterion #4: FAIL → PASS.**

*Implemented: SPEC §6, §7.1, §7.2 · TICKET-048 · `tests/test_turnover.py` · config
`no_trade_band: 0.03`, `buffer_rank: 80`.*

---

## 4. Finding 3 — Missing accounting invariants

Neither failure would have been caught by any existing test, because the protocol had no
**accounting invariants** — only statistical ones. Added as PROTOCOL §4.1, checked every period
of every backtest including inside CPCV paths:

1. Cash is never negative at any point in any period.
2. Positions + cash reconcile to NAV within 1e-6.
3. Every share sold was held (no implicit shorting via a sizing bug).
4. Projected turnover is checked **before** trading, not reported after.

A violation **raises and marks the run invalid** — never a warning. *TICKET-049.*

---

## 5. Verification

Amended spec, same data, same 54 quarters:

| Metric | Before | After | Status |
|---|---|---|---|
| Negative-cash quarters | 11 / 54 | **0 / 54** | PASS |
| Annualized turnover | 99.6% | **35.7%** | PASS (ceiling 60%) |
| Avg positions | 20.0 | 20.0 | within 15–25 |
| Buy shortfalls | n/a | 3, scaled pro-rata | no leverage |
| CAGR | 6.95% | 8.59% | **not claimed as a benefit — see §3** |

Static coherence audit across all docs, rules, config, Makefile, and hooks: **0 issues.**

---

## 6. What this says about the project

Three things worth carrying forward:

1. **Documents cannot validate themselves.** Both failures were invisible in prose and obvious
   within one simulation run. The spec was internally consistent, well-cited, and wrong.

2. **The obvious fix was the wrong fix.** A cash buffer is what most people would reach for; it
   made the problem worse in a way that only measurement revealed. That is a small, concrete
   instance of the project's whole thesis.

3. **We applied our own honesty rules to our own change.** The amended configuration shows a
   higher CAGR. The sensitivity sweep proves that improvement is noise, so it is not claimed —
   and there is now a test enforcing that it never gets claimed. If the project cannot do that
   to its own results, the reporting rules in `docs/07` are decoration.

### Limitations — state these when citing this document
- Synthetic data. Returns are meaningless; only the **mechanics** were tested.
- One realized path, one parameter set, one universe generator seed.
- Tax lots, wash sales, Sleeve E, and the LLM extraction path were **not** exercised — they need
  their own simulation before live use.
- The turnover/rank relationship should be re-confirmed on real data before funding.

**Recommended next simulation:** the tax engine and Sleeve E staged entry, which contain the
next-most-likely class of silent accounting error.
