# Build Tickets

One ticket per session, one branch, one PR. Done = acceptance criteria pass and `make test` green.

| Range | Area | Read first |
|---|---|---|
| 001-017 | Core trading system | docs/00-06 |
| 018-023 | Reporting engine | docs/07 |
| 024-029 | Sleeve E discovery | docs/08 |
| 030 | CPCV validation | docs/09 |
| 031-034 | Signal extensions | docs/10 |
| 035-037 | Tax engine | docs/11 |
| 038-041 | Research workflow | docs/12 |
| **042-046** | **From the open-source audit** | **docs/13** |

---

## Core (001-017) — abbreviated; full criteria in each module docstring

**T-001 store** — idempotent schema, append-only snapshots, `as_of()` guard. 1M rows filtered
in < 200ms. **T-002 SEC fundamentals** — `available_at = acceptance + 1 trading day`; AAPL
yields >= 40 quarters with no nulls; restatements flagged, originals retained. **T-003 prices**
— **raw OHLCV plus a corporate-action table; adjusted-only rejected**; AAPL 2020 split handled;
SPY total return within 10bps/yr; delisted tickers return a final price and reason.
**T-004 universe** — 2008 contains LEH/WM/BSC; 2000 has >= 300 now-dead tickers; size not
monotonically increasing; every exclusion has a reason. **T-005 macro/FF** — percent→decimal,
monthly table only, `YYYYMM` parsed. **T-006 durability** — matches a hand fixture to 2dp;
financials variant routes by SIC; three flags => excluded; no network or wall-clock.
**T-007 valuation** — reverse-DCF round-trips within 0.1%; non-convergence returns NaN and
excludes; floors before scoring. **T-008 momentum** — most recent month genuinely excluded;
dividends included. **T-009 overlays** — only Form 4 code `P`; political and 13F use `filed_at`;
outside top-40 gets zero; each overlay in its own column. **T-010 proposals** — every sell cites
S1-S5; wash-sale blocks a loss-repurchase; blank "mistake" line. **T-011 engine** — no-lookahead
test passes; delisting returns applied; cash reconciles. **T-012 costs** — 1x/2x/3x multiplier;
ST vs LT rates; wash-sale defers into basis. **T-013 stats** — Sharpe matches quantstats to 1e-6.
**T-014 ablations** — all nine variants from one command; Newey-West; states whether |t| > 2.
**T-015 broker** — asserts `paper-api`; KILL exits before auth; requires the flag; re-validates
independently; chaos tests reconcilable. **T-016 reconcile** — mismatch blocks submit.
**T-017 memo** — leads with Sleeve C+E vs VTI; every sell names its rule; **includes the bear
case**; blank "mistake" line; 48h time stated.

## Reporting (018-023)
**T-018 TWR/MWR + risk** — hand fixture where TWR and MWR visibly differ; changing deposit SIZE
leaves TWR unchanged and moves MWR. **T-019 inference** — **stationary block bootstrap, not
IID**, verified on synthetic GARCH-like data where IID intervals are too narrow; CI returns NaN
below 8 periods; identical series => `significant=False`; **DSR raises if experiment_log.csv is
missing** and strictly decreases as trials rise. **T-020 attribution** — Brinson effects sum to
excess to 1e-10; interaction is its own column; Carino linking reproduces cumulative excess.
**T-021 narrative** — rejects banned phrases, "outperformed" without a CI, no negative
contributor, unqualified "alpha"; passes for 20 randomized inputs including bad-loss cases; the
writer **raises** rather than writing a failing narrative. **T-022 research export** — seven
artifact types; methodology.md pins everything; disclosure block everywhere; 300dpi; regeneration
byte-identical. **T-023 orchestration** — all five types generate; **`import
durable.reporting.report` does NOT transitively import `durable.execution`** (assert on the
import graph); deterministic JSON; no network.

## Sleeve E (024-029)
**T-024 universe** — rejects every OTC ticker incl. 24-month history; rejects sub-$5, cap outside
range, thin ADV, small float, unprofitable; **missing data => excluded, never imputed**; all 11
auto-disqualifiers tested; a synthetic CHOW-like profile rejected on >= 3 independent grounds;
**safety constants not config-readable**. **T-025 manipulation** — any hit => `is_clean=False`;
returns all flags including passed ones; toxic-financing language caught; social velocity does
NOT fire alongside an 8-K; **perfect fundamentals + one flag still excluded**. **T-026 neglect**
— 13F `available_at = filed_at`; caps at 25; raw inputs returned; module comment states the
premium is contested. **T-027 screens** — all seven; User-Agent asserted; <= 10 req/sec; CIK
zero-padding; only code `P`; multi-screen hits add **no** points; empty result is valid.
**T-028 score** — durability gate before anything else; small-cap peer ranking with a documented
fallback; EV/EBIT > 30 excluded; uncited quality claims score 0. **T-029 tranches** —
`size_tranche` returns the MINIMUM of four constraints; sub-minimum returns 0.0, never rounds up;
**explicit test that a 50% drawdown with unchanged fundamentals does NOT unlock T2**; score < 60
cancels permanently; E1 graduation reported as success; E4 exits regardless of P&L; dossier has
all nine sections and passes `validate_narrative()`.

## Validation (030)
**T-030 CPCV + PBO** — N=10,k=3 gives exactly 120 paths · **purging** tested on a synthetic
overlapping-label dataset where omitting it demonstrably inflates performance · embargo =
max(1 quarter, 1% of n_periods) · a deliberately overfit fixture yields PBO > 0.5 · reports
mean/median/stdev/5th-percentile and fraction beating benchmark · scores cached by
(as_of, snapshot_id) · **locates the walk-forward result's percentile in the distribution** ·
seed logged · wired into kill criteria as #6.

## Signals (031-034)
**T-031 LLM extraction** — fixed JSON schema; **uncited claims score 0** (explicit test); cached
by (accession, prompt_version, model_version); `available_at` from the filing; temperature 0;
low confidence => null; **contamination guard raises** unless `allow_contaminated=True`;
`audit_sample(0.10)` writes to extraction_audit.csv. **T-032 13F** — `available_at = filed_at`
(test asserts `period_end` is never used); **CUSIP-based matching** stable across mergers and
ticker changes; change classification; managers from config with **no performance field**
(assert its absence); overlay capped ±2. **T-033 distance-to-default** — solves the two-equation
system; reproduces a published worked example within 1e-4; thresholds applied; **not applied to
financials**; non-convergence returns NaN and flags; **uses no new data source**.
**T-034 short interest + credit** — `available_at = publication_date`; thresholds by sleeve;
days-to-cover reported; credit widening triggers an Event Report **not** an automatic sell;
missing bond data degrades gracefully (absence is not a signal).

## Tax (035-037)
**T-035 lots** — `Decimal` throughout (assert no float in any money path); 6-decimal fractional
shares; after-tax-optimal selection with a test where it disagrees with HIFO and wins; every
selection logs its reason. **T-036 harvest + wash sale** — 61-day window; **scans ALL accounts**
with an explicit taxable-sale + Roth-purchase test reported as a PERMANENT loss; DRIP counts;
disallowed loss ADDED to basis with holding period inherited; taxable-only; refuses to harvest a
name the screen wants this quarter; replacement is a sector ETF proxy. **T-037 after-tax** —
after-tax alongside pre-tax for every variant; **tax alpha vs naive-FIFO counterfactual**;
carryforward across years with the $3,000 cap; models both "use now" and "carry forward".

## Research (038-041)
**T-038 journal** — empty `disconfirming_evidence` raises; confidence required in [50,99] before
any outcome; entries immutable once resolved; predictions need a resolution date; auto-creates
entries during rebalance. **T-039 calibration** — Brier matches a hand fixture; curve returns bin
counts with sparse bins flagged; overconfidence ratio; discrimination; **breakdown by emotional
state**; override performance cross-referenced. **T-040 literature** — pyzotero + Better BibTeX;
claims.csv schema enforced including **`contradicted_by`**; a claim used in any doc without a
ledger entry raises in CI. **T-041 preregistration** — a hypothesis must be committed before its
test runs (compares git timestamps, **raises on HARKing**); experiment_log gains the new columns;
**`make reproduce COMMIT=<hash>` regenerates byte-identically**; seeds pinned.

---

# From the open-source audit (042-046) — read docs/13 first

## TICKET-042 — Leakage firewall
**Files:** `src/durable/data/firewall.py`, `tests/test_firewall.py`

An independent assertion layer on top of `store.as_of()`, adapted from the `agent-backtest-lab`
pattern (docs/13 §2.2). The store protects paths that go through the store; the firewall catches
the ones that don't.

- [ ] `assert_no_future` raises `LeakageError` naming the offending rows when any
      `available_at > as_of`
- [ ] `assert_raw_prices` raises `AdjustedPriceError` on a frame with adjusted prices and no raw
      OHLCV columns — **and a test proves an adjusted series differs from the historical series
      after a split**, which is the reason the rule exists
- [ ] `assert_lagged_disclosure` catches a 13F frame whose `available_at` tracks `period_end`
      rather than `filed_at`, and the same for STOCK Act and short interest
- [ ] `audit(conn, as_of)` sweeps every table and returns violations; empty = clean
- [ ] Every public data function ends with a firewall call — enforced by a test that greps the
      module for `return` statements not wrapped
- [ ] Violations logged to `firewall_violations`; the count is a process-health metric on every
      report and **must be zero**
- [ ] `LeakageError` subclasses `AssertionError` deliberately — it must never be caught and
      handled; if it fires, a result is invalid and must be discarded

## TICKET-043 — Factor IC analysis
**Files:** `src/durable/factors/ic.py`, `tests/test_ic.py`

docs/09 §7 and docs/13 §2.3. Answers what the portfolio backtest cannot: **is the factor itself
predictive?**

- [ ] `rank_ic` uses **Spearman**, not Pearson — a test on a fat-tailed fixture shows Pearson is
      dominated by two outliers while Spearman is stable
- [ ] `ic_summary` returns mean, std, IR, t-stat, hit rate, n_periods
- [ ] **Flags |mean IC| > 0.15 loudly as suspected look-ahead** and recommends backtest-validator
- [ ] `ic_decay` across 1/2/4/8 quarters; a synthetic factor with a known 2-quarter half-life
      reproduces it
- [ ] `quantile_returns` + `is_monotonic`; a non-monotonic fixture with a large top-minus-bottom
      spread is correctly reported as a **tail effect, not a factor**
- [ ] `factor_autocorrelation` gives implied turnover before the buffer rule
- [ ] `sector_neutral_ic` — a fixture that is purely a sector bet shows strong raw IC and
      near-zero sector-neutral IC
- [ ] Every IC run appends to `experiment_log.csv` — an IC test is a trial
- [ ] IC table appears in every performance report

## TICKET-044 — Almgren-Chriss market impact
**Files:** `src/durable/backtest/impact.py`, `tests/test_impact.py`

- [ ] Temporary impact scales with `participation ** 0.5` — doubling size raises cost ~1.41x,
      not 2x (explicit test)
- [ ] Permanent impact is linear and does not revert
- [ ] `total_cost_bps` = half-spread + temporary + permanent, scaled by `multiplier`
- [ ] A Sleeve E order at 1% of ADV in a thin name costs materially more than the old flat-tier
      model — quantify the difference in the test
- [ ] Coefficients published in `methodology.md`; an impact model is an assumption, not a
      measurement, and a reader must be able to re-run with their own

## TICKET-045 — LLM contamination / alpha-decay test
**Files:** `src/durable/signals/contamination.py`, `tests/test_contamination.py`

Adapted from Look-Ahead-Bench (docs/13 §1): distinguish predictive capability from memorization
by measuring **performance decay across the model's training cutoff.**

- [ ] `alpha_decay_test` compares feature IC before vs after `training_cutoff`
- [ ] Verdicts: `insufficient_data` (< 8 periods either side) · `contaminated` (pre-cutoff IC
      exceeds post by > 50% AND p < 0.05) · `suspected` · `clean`
- [ ] **`clean` means "we looked and found no evidence", never "proven clean"** — the wording is
      asserted in a test because it will be quoted in the paper
- [ ] `placebo_test` shuffles ticker labels within each date; comparable IC means the "signal" is
      a panel artifact
- [ ] `entity_anonymization_check` flags prompts leaking company identity; identity-dependent
      tasks are recorded so the verdict is interpreted accordingly
- [ ] The verdict is written into `methodology.md` and every research artifact using the feature
- [ ] Seeds pinned for the placebo shuffle

## TICKET-046 — Bear-case requirement
**Files:** `src/durable/reporting/memo.py`, `src/durable/discovery/dossier.py`,
`tests/test_bear_case.py`

docs/13 §2.5. Takes the structured-dialectic idea from multi-agent trading frameworks and
discards the autonomy.

- [ ] Memo generation **raises** if `bear_case` or `falsifiers` is empty
- [ ] Exactly three falsifiers required, each a specific observable
- [ ] Every bear-case claim carries a filing citation; uncited claims are stripped with a warning
- [ ] Bear case is copied verbatim into `decisions.csv:disconfirming_evidence`
- [ ] **Required for every Sleeve E buy**; warned-but-allowed for Sleeve C
- [ ] Bear text passes `validate_narrative()` — no promotional language in either direction
- [ ] "No bear case could be constructed" is a permitted value **only** with a written record of
      what was checked (filings, short interest, credit, insider activity)

---

# From the trading simulation (047-049) — read docs/01 and SPEC §7

These tickets exist because an end-to-end simulation of the spec **as originally written**
failed two of its own requirements. See the change log in `docs/00` v1.3.

## TICKET-047 — Sequenced execution
**Files:** `src/durable/execution/sequencer.py`, `tests/test_sequencing.py`

**Measured problem:** negative cash in **11 of 54 simulated quarters** — unmodelled leverage a
real broker would reject. **A cash buffer does not fix it** (tested 0.5/1.0/1.5/2.0% → 4/4/7/8
negative quarters; larger buffers were worse).

- [ ] Sells execute first; proceeds recorded net of cost
- [ ] `affordable = cash / (1 + cost_rate)` — cost reserved on the buy side
- [ ] Buys exceeding affordable cash scale **pro-rata, not priority-ordered** (priority funding
      would silently concentrate the portfolio exactly when cash is tight)
- [ ] `assert_invariants` raises on negative cash at any step — a violation invalidates the run
- [ ] Every sell carries `lot_ids`; never lets the broker default to FIFO
- [ ] Simulation-derived regression test: the fixture that produced 11 negative quarters now
      produces **0**
- [ ] Shortfall quarters are logged and surfaced in the quarterly report

## TICKET-048 — No-trade band and turnover control
**Files:** `src/durable/portfolio/construct.py`, `src/durable/portfolio/diff.py`,
`tests/test_turnover.py`

**Measured problem:** the spec as written produced **99.6% annualized turnover** — kill
criterion #4 fires immediately. Decomposition: **62.4pp from name changes, 37.2pp from drift
back to equal weight alone**, before any name changed.

- [ ] Continuing holdings trade only when drift > `no_trade_band` (3% of NAV)
- [ ] Name changes and constraint breaches always execute, regardless of band
- [ ] `projected_turnover()` is checked **before** trading, not reported after
- [ ] Above the 60% ceiling, the rebalance reduces to name changes + constraint breaches, and
      logs the event
- [ ] Regression test: band 0% → drift turnover ≈37pp; band 3% → ≈7pp
- [ ] Buffer rank 80 (SPEC §6). A test asserts the value is sourced from the turnover
      constraint, with a comment forbidding tuning it on returns

## TICKET-049 — Accounting invariant harness
**Files:** `tests/test_invariants.py`, `src/durable/backtest/engine.py`

PROTOCOL §4.1. Checked every period of every backtest, not just at the end.

- [ ] Cash never negative at any point in any period
- [ ] Positions + cash reconcile to NAV within 1e-6
- [ ] Every share sold was held — no implicit shorting via a sizing bug
- [ ] A violation **raises** and marks the run invalid; it is never a warning
- [ ] The harness runs inside CPCV paths too, not only the headline walk-forward
