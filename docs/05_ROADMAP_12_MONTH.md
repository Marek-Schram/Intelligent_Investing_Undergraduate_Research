# 05 — 12-Month Roadmap

~6-10 focused hours/week alongside school and an internship.

## Phase 0 — Foundation (Weeks 1-2)
`uv`, Python 3.12, `uv sync` · free accounts: SEC identity, FRED, Alpaca **paper**, Zotero ·
edgartools returning Apple's income statement · DuckDB store (T-001) · Claude Code: MCP servers,
verify **8 rules, 11 skills, 9 subagents, 4 hooks** load · **commit
`research/protocol/preregistration.md` before any backtest.**

## Phase 1 — Data layer (Weeks 3-8) — 60% of total work
T-001 store · T-002 SEC fundamentals with `available_at` · T-003 **raw** prices + corporate
actions · T-004 universe + survivorship tests · T-005 FRED + Ken French · **T-042 firewall**.

**Artifact:** `make ingest` builds >= 1,500 tickers × 10 years; `make leakage-audit` returns
zero violations; no-lookahead and universe-integrity tests pass.

**Checkpoint:** can you produce the exact eligible ticker set as of 2014-05-16, including
companies that no longer exist? If no, stop. Everything downstream is worthless.

## Phase 2 — Factors (Weeks 9-14)
T-006 durability · T-007 valuation + reverse-DCF · T-008 momentum · T-009 overlays ·
**T-043 IC analysis**.

**Artifact:** every sub-score matched to a hand-built spreadsheet for 3 companies, **plus an IC
report per factor.** A factor with no IC does not ship, regardless of how good the portfolio looks.

## Phase 3 — Backtest and validation (Weeks 15-24)
T-011 walk-forward · T-012 costs + tax · **T-044 Almgren-Chriss impact** · T-013 stats ·
T-014 ablations · **T-030 CPCV + PBO**. Design period only. Log every trial. One validation pass.

**Artifact:** `reports/backtest_v1.html`, a CPCV distribution with PBO, factor IC table, and a
2-page written conclusion.

**The real decision point:**
- Alpha survives, 1-3%/yr, stable, PBO < 0.35, factors show IC → proceed
- No alpha beyond factor exposure, or PBO > 0.50, or no factor IC → **the most valuable lesson
  in the project.** Simplify to a factor-ETF tilt, or continue smaller as an explicit education
  project. Both are good outcomes. Neither is failure.
- Alpha > 8%/yr → you have a bug. Look-ahead in the fundamentals join, a missing delisting
  return, adjusted prices, or LLM contamination.

## Phase 3.5 — Reporting (Weeks 20-26, overlapping)
T-018 TWR/MWR + risk · T-019 bootstrap, Sharpe test, MinTRL, DSR · T-020 Brinson + factor
attribution · T-021 narrative + honesty validator · T-022 research export · T-023 orchestration.

## Phase 4 — Signals and tax (Weeks 25-34)
T-031 LLM extraction · **T-045 contamination / alpha-decay test** · T-032 13F · T-033
distance-to-default · T-034 short interest + credit · T-035/036/037 tax.
**Re-run ablations. Every new signal must earn its place or get cut.**

**Artifact:** an ablation table showing what each extension contributed — **including the ones
that contributed nothing.** That table is a genuine research finding.

## Phase 5 — Discovery and paper trading (Weeks 23-48, parallel)
T-024→029 Sleeve E · **T-046 bear-case requirement** · T-010 proposals · T-015 Alpaca paper ·
T-016 reconciliation · T-017 memo · T-038 journal · T-039 calibration.

**Artifact:** four quarterly memos, four research bulletins, a paper track record compared
against backtest predictions, and >= 40 scored journal entries.

## Phase 6 — Decision (Month 12)
Review the six kill criteria. Held up → fund with **real money at 10% of portfolio maximum**,
Roth if possible. Mixed → another year of paper, costs only time. Kill criteria fired → move to
a quality/value factor ETF and keep the codebase; it is a genuinely strong portfolio piece.

**Also due:** your first calibration report. Likely more interesting than your returns, and it
converges far faster.

## Reading (~1/month)
1. **The Intelligent Investor** — Ch. 8 and 20 twice · 2. **The Little Book That Still Beats
the Market** · 3. **Quantitative Value** — closest published thing to this · 4. **What Works on
Wall Street** · 5. **Expectations Investing** — the reverse-DCF comes from here ·
6. **The Psychology of Money** — read it the first time you're down 25% ·
7. **Advances in Financial Machine Learning** — the overfitting, CPCV, DSR, and PBO chapters.
**Operational, not background: docs/09 implements it.** · 8. **Poor Charlie's Almanack** ·
9. **Superforecasting** — directly relevant to the calibration work.

Also read Piotroski (2000) and Walkshäusl (2020) directly — free, readable, and you are
implementing them.

## Beyond investing
You will have built a point-in-time financial database with an independent leakage firewall, a
walk-forward *and* CPCV validation framework, factor IC analysis, a guarded broker integration,
a citation-enforced LLM extraction pipeline with a contamination test, a tax-lot engine, and a
calibration study. That maps directly onto actuarial work — reserving as-of dates are the *same*
point-in-time problem. Write the README so a recruiter gets it in 90 seconds.
