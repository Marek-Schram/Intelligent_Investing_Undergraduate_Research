# 07 — Automated Performance Reporting

Answers, on a schedule: **what is the system doing, how well, and how confident should anyone
be?** Built for a research project: reproducibility, uncertainty quantification, machine-readable
export.

## 0. Plain-English
Every week (deeply every quarter) the system writes its own report card: what it owns, what
changed, how much it made or lost, how that compares to just buying the whole market, and
whether the difference is big enough to mean anything. **It is not allowed to only show good news.**

## 1. Types
Pulse (weekly, one screen) · Quarterly Review · **Research Bulletin** (the paper's raw material)
· Event Report (triggered) · Annual Assessment (the kill-criteria decision).
Markdown + HTML + a machine-readable JSON sidecar.

## 2. Contents — least flattering first
**2.1 Headline.** Sleeve C+E vs VTI since inception, with the **95% CI on excess return** and
periods observed vs periods needed for significance. CI crossing zero => the report says plainly:
*"This difference is not statistically distinguishable from luck."*

**2.2 Returns — both methods.** **TWR** (chain-linked, removes cash-flow timing) measures the
*strategy*; **MWR/IRR** measures *your experience as an investor*. The gap is itself a finding.
Say "GIPS-style time-weighted return," never "GIPS-compliant."

**2.3 Risk.** CAGR, vol, Sharpe, Sortino, Calmar, max DD + duration, skew, kurtosis, best/worst
month, win rate, up/down capture.

**2.4 Attribution.** **Brinson** (allocation vs selection vs interaction, Brinson-Fachler with
Carino linking) and **FF5+MOM factor regression** — alpha, or repackaged factor exposure you
could buy for 15bps? **Report the interaction term and the factor residual explicitly rather
than redistributing them.** Plus a per-position contribution table sorted by absolute contribution.

**2.5 Uncertainty.** **Stationary block bootstrap** CIs (not IID — squared returns are
persistent) · **Ledoit-Wolf robust Sharpe-difference test** (Jobson-Korkie/Memmel is invalid
under fat tails) · **minimum track record length** next to every Sharpe · **Deflated Sharpe** ·
**PBO from the latest CPCV run** · Monte Carlo for the range of plausible outcomes.

**2.6 Factor IC.** Per factor: IC, information ratio, t-stat, decay, quantile monotonicity.
**A portfolio can look fine while every underlying factor has zero information content** —
this table is how you find out.

**2.7 Tax.** Realized ST/LT · harvested losses and carryforward · **tax alpha vs a naive-FIFO
no-harvesting counterfactual** · wash-sale disallowances with triggering trades named ·
"wait N days" list · after-tax return alongside pre-tax.

**2.8 Process health.** Turnover vs backtest · tracking error · holding period · cash drag ·
sector concentration · fill quality · reconcile status · **override count** · extraction audit
error rate · **firewall violations (must be zero)**.

**2.9 Kill-criteria scoreboard.** All six, PASS/WARN/FAIL. Every report, not an appendix.

**2.10 Sleeve E section.** Reported separately: return, hit rate, tranche status, graduations,
and **the count of candidates excluded by the manipulation screen** — itself a finding about
market structure.

**2.11 Narrative.** 4-8 sentences:
> *"Sleeve C returned +3.1% versus +4.4% for VTI, trailing by 1.3 points. The shortfall came
> almost entirely from selection within Industrials, where two holdings fell more than 15%.
> Since inception the strategy leads by 0.8 points, but the 95% CI spans −4.1 to +5.7, so it
> remains indistinguishable from noise. Factor regression attributes most of the return to
> quality and value loadings, with alpha of 0.4% annualized (t = 0.3) — not significant. PBO
> from the last CPCV run was 0.41. Mean rank IC on the durability factor was 0.031 (t = 2.1).
> Turnover ran 22%, below the 60% kill threshold. Tax alpha added 0.6%. No red flags triggered."*

Enforced in `validate_narrative()`: lead with the comparison · never "outperformed" without the
CI adjacent · never call an insignificant result skill · name best AND worst contributor by
ticker · state one thing that went wrong · no forward-looking language.

## 3. Research outputs
`reports/research/YYYY-QN/`: metrics.json · returns.csv · attribution.csv · positions.csv ·
factor_ic.csv · tables/*.tex · figures/*.png (300dpi) · **methodology.md**.

`methodology.md` pins snapshot IDs, git commit, config hash, seeds, cost and impact assumptions,
bootstrap method and block size, LLM model and prompt versions, contamination verdict, and trial
count. **Without it, a result in your paper is an anecdote.**

Auto-appended, non-removable disclosure:
```
Sample period: YYYY-MM-DD to YYYY-MM-DD (N periods).
Status: <paper|live>. Costs modeled: <spread, slippage, Almgren-Chriss impact, tax>.
Trials logged prior to this result: <N>.  PBO: <x.xx>.  LLM contamination verdict: <verdict>.
Results are from a single realized path of one strategy on one universe and should not be
interpreted as evidence of a repeatable edge.
```

## 4. Anti-vanity guardrails
Benchmark first · no cherry-picked windows (since-inception, YTD, trailing 12m — all three) ·
uncertainty never optional (`X.X% (CI unavailable: N < 8 periods)`) · kill criteria on every
report · losses named as specifically as gains · no forward-looking language · small-sample
banner until 12 quarters.

## 5. Implementation
quantstats (tearsheets) · pybrinson (Brinson) · statsmodels (FF5+MOM, Newey-West) ·
arch.bootstrap (block bootstrap) · jinja2 (templating). **Pure functions of (returns, holdings,
benchmark, snapshot_id).** No network at report time. Never imports `execution/` — a test and a
hook both enforce it, which is what makes unattended scheduling safe.
