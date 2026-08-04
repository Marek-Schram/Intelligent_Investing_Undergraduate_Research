# 10 — Signal Extensions

Four additions that earn their place, plus explicit rejections. Every one must be **ablatable** —
if the backtest can't isolate its contribution, it doesn't ship.

## 0. Plain-English
1. **Reading filings with AI** — an AI can read 200 annual reports and pull out specific facts.
2. **Watching what great investors buy** — big funds must publicly report holdings quarterly.
3. **Checking whether the bond market is scared** — bondholders usually panic before shareholders.
4. **Checking who's betting against it** — not to copy them, but to ask what they see.

None of these picks stocks. They add evidence to a decision durability and valuation already made.

## 1. LLM filing analysis
**The evidence.** Chicago Booth researchers gave GPT-4 **standardized, anonymized** financial
statements — no names, no narrative, no industry context — and asked it to predict the direction
of future earnings. It **outperformed human analysts**, with its advantage concentrated exactly
where analysts struggle, matched a narrowly-trained ML model, and the result did not come from
training memory. Trading strategies on its predictions produced higher Sharpe and alpha.

**The anonymization detail is the whole point:** it was doing *analysis*, not recalling that
Apple did well.

**The counter-evidence** (docs/13 §1): LLM *timing* strategies evaluated over two decades and
100+ symbols see their reported advantages deteriorate badly, behaving over-conservatively in
bull markets and over-aggressively in bear markets. Pretraining contamination means a model
asked about 2023 may recite "NVIDIA surged 190%" rather than infer it.

**So: extraction, not prediction.** We ask for facts a human analyst would extract, each with a
citation, and feed those into the deterministic score.

| Task | Feeds |
|---|---|
| Risk-factor delta vs prior 10-K | Red flags (SPEC §2.5) |
| Red-flag language (going-concern, auditor change, covenants) | Exclusions |
| Revenue durability markers (contract length, recurring %, sole-source) | Quality evidence |
| Customer/supplier concentration | Quality evidence |
| Segment detail | Durability trend |
| Capital allocation language | Growth durability |
| Guidance-language shift, quietly dropped metrics | Red flags |
| Toxic financing detection | Sleeve E manipulation screen |

**Non-negotiable rules.** Every claim carries a filing citation or scores zero · structured JSON
only, enum-constrained · cached and versioned by (accession, prompt_version, model_version) ·
`available_at` from the filing · temperature 0, model version logged · **contamination guard**
raises when the window predates the training cutoff · **alpha-decay test** (TICKET-045) measures
IC on both sides of the cutoff · 10% quarterly audit against actual filings.

## 2. Institutional conviction (13F)
**Evidence.** Managers can pick stocks, but diversification buries their best ideas;
high-conviction concentrated positions are the signal. QuantPedia rates confidence "Strong" on
~1.26% monthly alpha in the source paper (1991-2005). A 2024 study of 150,000+ cloned portfolios
found top-quartile clones exceeded the S&P by 24.3% annualized risk-adjusted.

**Caveats, severe.** 13F covers **long US equity only** — no shorts, options, bonds, cash, or
international. Filings appear **~45 days after quarter-end**, so positions may have changed.
Clone simulations assume buying at close on filing day, which no real investor can do, and model
no fees, slippage, or costs.

**Use:** primarily a **seventh screen** for candidates; secondarily a ±2 overlay gated to top-40.
+2 if >=3 tracked managers hold as top-10 AND >=1 added; +1 if >=3 hold; −1 if >=3 exited.
Managers fixed in `config/managers.yaml` on criteria set in advance (>=10 years filing, top-10
>= 50% of AUM, style-consistent, low turnover) — **never "whoever did well recently."**
`available_at = filed_at`, always.

## 3. Distress and credit early warning
**Distance-to-Default (Merton/KMV).** Equity as a call option on firm assets struck at debt face
value; back out asset value and volatility from observable equity value and volatility.

$$DD = \\frac{\\ln(V/D) + (\\mu - \\tfrac{1}{2}\\sigma_V^2)T}{\\sigma_V\\sqrt{T}}, \\quad EDF = N(-DD)$$

Solve simultaneously: $E = V N(d_1) - De^{-rT}N(d_2)$ and $\\sigma_E E = N(d_1)\\sigma_V V$.

**Why it earns a place:** forward-looking and market-implied rather than a backward-looking
accounting ratio, explicitly used in early-warning systems, and it needs **only data we already
have** — equity price, equity vol, debt, DGS10. Zero marginal data cost.
DD < 2.0 => −5 red flag; DD < 1.0 => exclusion (1.5 for Sleeve E). Not applied to financials.

**Credit spreads.** Credit moves first: bondholders' asymmetric payoff makes them obsess over
downside, credit desks sit closer to treasurers and refinancing calendars, and rating-based
mandates force mechanical selling. Lehman, Hertz in early 2020, regional banks in March 2023,
and Bed Bath & Beyond all showed spreads blowing out weeks before equity capitulation. Free from
**FINRA TRACE**. Monitoring only: >150bps widening vs the issuer's own trailing baseline with no
sector move triggers an Event Report — a prompt to look, not an automatic sell.

## 4. Short interest as a risk flag
FINRA reports twice monthly, published ~11 business days after settlement — **11+ days stale on
release.** Free from FINRA/NYSE/Nasdaq. Average S&P 500 name carries 2-3% of shares outstanding;
some exceed 30% of float.

**We use this in the opposite direction from most retail interest in it.** Not hunting squeezes —
that's a trading strategy. High short interest on a name our screen likes is a **prompt to find
out what the shorts see that our fundamentals-based screen doesn't.**

> 15% of float => −3 and a mandatory research note · > 25% => **exclusion** · days-to-cover > 10
=> flag for exit liquidity · Sleeve E > 10% => **exclusion**. `available_at = publication_date`.

## 5. Explicitly rejected
| Capability | Why |
|---|---|
| Options-implied signals | Spec forbids options; paid data; short-horizon mismatch |
| Social sentiment | Contradicts `.claude/rules/speculation-limits.md` — unsolicited social sourcing is a *disqualifier*. Cannot ban it as a source and use it as a signal |
| Macro regime switching | Weak out-of-sample evidence; parameter-rich on ~112 observations |
| Alternative data | No genuine retail access; vendors largely repackage public data |
| Full direct indexing | Needs hundreds of positions. We harvest its tax-lot logic instead (docs/11) |
| Triple-barrier, meta-labeling, fractional differentiation | docs/09 §5 |
| Short selling, leverage, crypto | CLAUDE.md rule 3 |
| Analyst estimate revisions | Predictive but paid, and Sleeve E deliberately targets names with no analysts |
| Insider *sales* as a signal | Already handled — routine and 10b5-1 sales are noise |
| **LLM price/return prediction** | **docs/13 §1 — structurally unbacktestable before the training cutoff** |
| **Automated factor mining** | **docs/13 §3 — makes the trial count unknowable and preregistration meaningless** |
