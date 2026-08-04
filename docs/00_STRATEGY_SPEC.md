# 00 — Strategy Specification

The contract. Code implements exactly this. To change a rule, change it **here first**, dated,
then change the code. (First Law: research theories, not backtests.)

## 0. Plain-English
Buy ~20 boring, financially strong, reasonably priced companies; hold for years. A checklist
picks them: **is this a good business** · **is the price sane** · **is the market agreeing yet**.
Small adjustments for red flags, and tiny bonuses if insiders, members of Congress, or
concentrated fund managers have been buying.

## 1. Universe (point-in-time, every rebalance)
US-listed common stock (NYSE/NASDAQ/AMEX incl. ADRs) · cap >= $2.0B · median 60-day dollar
volume >= $10M · price >= $5 · >= 8 quarters filed · exclude pre-revenue biotech (SIC 2836/8731,
revenue < $50M), SPACs, closed-end funds, IPOs < 24 months. Banks/insurers (SIC 60xx-64xx) use
the financials variant §2.6. **Delisted companies remain in historical universes.**

## 2. Durability Score (0-50)
**2.1 Piotroski F-Score (0-9 → 0-14).** Net income > 0 · CFO > 0 · ROA improving · CFO > NI ·
LT debt/assets down · current ratio up · shares not up (>1% tolerance) · gross margin up ·
asset turnover up. `f_points = f_score / 9 * 14`

**2.2 ROIC (0-14).** `NOPAT = EBIT × (1 − tax_rate[0.10,0.35])`;
`InvCapital = total_debt + equity − cash`; `ROIC = NOPAT / avg(InvCapital_t, InvCapital_{t-1})`.
Score the **5-year median**, sector-percentile ranked. Consistency is the durable signal.

**2.3 Cash & balance sheet (0-12).** Three sub-scores, 4 each: FCF conversion (5y median
FCF/NI, clipped [0,2]) · net debt/EBITDA (4 if <=1.0, 0 if >=4.0) · interest coverage
(4 if >=10x, 0 if <=2x).

**2.4 Growth durability (0-10).** Revenue-growth STABILITY `4 × (1 − normalized_stdev)`,
winsorized 5/95 — steady beats fast · gross-margin trend, sector-ranked (3) · 5y share-count
change (3 if shrinking, 0 if diluting >3%/yr).

**2.5 Red flags (−0 to −18).** Three triggers => **excluded**.

| Flag | Detection | Penalty |
|---|---|---|
| Accrual bloat | (NI − CFO)/assets > 10% | −5 |
| Receivables blowout | AR growth > 1.5× revenue growth, 2 yrs | −4 |
| Inventory blowout | same for inventory | −3 |
| Goodwill heavy | goodwill/assets > 40% | −3 |
| Serial dilution | shares +>5%/yr for 3 yrs | −5 |
| Going-concern language | phrase match | **exclude** |
| Auditor change + restatement in 12m | filing metadata | **exclude** |
| Altman Z < 1.8 | standard formula | −5 |
| Distance-to-default < 2.0 | Merton/KMV (docs/10 §3) | −5 |
| Distance-to-default < 1.0 | | **exclude** |
| Short interest > 15% of float | FINRA, publication date | −3 |
| Short interest > 25% of float | | **exclude** |

**2.6 Financials variant.** ROE for ROIC · Tier-1 percentile (banks) or combined ratio
(insurers) for net-debt/EBITDA · drop FCF conversion, redistribute to ROE. No Merton DD.

## 3. Valuation Score (0-35)
EV/EBIT inverted, sector percentile (10) · FCF/EV (10) · shareholder yield (5) · reverse-DCF
implied growth gap (10).

**3.1 Reverse-DCF.** Solve for the growth the price already implies:
`EV = Σ_{t=1..10} FCF_0(1+g)^t/(1+WACC)^t + TV`, `TV = FCF_10(1+g_term)/(WACC−g_term)/(1+WACC)^10`,
`g_term = 2.5%`, `WACC = DGS10 + 5.0% ERP, floored at 8%`.
`gap = trailing_5y_FCF_CAGR − g_implied`. Positive gap = market demands less growth than
delivered. Sector percentile × 10; implied growth > 20% scores 0.

**3.2 Hard floors.** Exclude if EV/EBIT > 45 or EBIT <= 0 · 5y median FCF <= 0 · implied
growth > 25%.

## 4. Momentum and trend (0-15)
A *timing tax reducer*, not a prediction. 12-1 total return, sector-ranked (10) · price above
200-day SMA (5; a score component, not an exclusion).

## 5. Overlays — tie-breakers only, gated to top-40 base rank
**5.1 Insider (±3).** Form 4, 6 months. Only code `P` counts; `F` and routine 10b5-1 are noise.
+3 if >=2 officers/directors bought >= $250k aggregate with no simultaneous 10b5-1; +1 for one;
−2 for net open-market selling > 2% of insider-held shares.

**5.2 Political (±2).** STOCK Act PTRs, **`filed_at` not `traded_at`** (45-day lag is real).
+2 if >=3 members bought in 90 days with committee jurisdiction; +1 without; −1 if >=3 sold.
*Limits: 45-day lag, broad amount ranges, mixed and post-2012-weaker evidence.*

**5.3 Institutional conviction (±2).** 13F, **`available_at = filed_at`**. Managers fixed in
`config/managers.yaml`: >=10 years filing, top-10 >= 50% of AUM, style-consistent, low turnover.
Never "whoever did well recently." +2 if >=3 hold as top-10 AND >=1 added; +1 if >=3 hold;
−1 if >=3 exited. *Limits: long US equity only — no shorts, options, bonds, cash, international.*

Total overlay range −5 to +7, **clipped to ±5**.

## 6. Composite and selection
`base = durability + valuation + momentum` (0-100); `composite = base + overlays`, clipped.
Build PIT universe → drop hard exclusions → rank → **target 20**, holdings retained while in
the **top 80** (buffer zone; the single biggest turnover reducer) → fill from the top.

*Buffer rank is set by the turnover constraint (§7.2), never by returns.* Measured sensitivity:
turnover falls monotonically with rank — 55→70.9%, 70→50.9%, 80→35.7%, 90→27.8%, 105→21.9%
annualized. That relationship is structural. The corresponding CAGRs were **non-monotonic**
(7.36 / 6.62 / 8.59 / 6.58 / 8.13%), i.e. noise. Rank 80 is the lowest round value comfortably
inside the 45% target with margin. **No return improvement is claimed and none was demonstrated.**

## 7. Sizing and rebalancing

Equal weight, then caps, then renormalize. Max position **6%** at purchase, trim above 12% ·
max GICS sector **25%** · 15-25 positions; fewer than 15 qualify => hold cash · new capital
deploys at the next scheduled rebalance.

### 7.1 No-trade band (added v1.3 — see change log)
A continuing holding is **only traded if its drift from target exceeds 3.0% of portfolio NAV.**
Name changes (entries and exits) are always executed; only *rebalancing back toward equal
weight* is banded.

Rationale, measured: in simulation, forcing every position back to equal weight each quarter
generated **37 percentage points of annualized turnover on its own** — 37% of all turnover,
purely from drift, before a single name changed. A 3% band cuts that to ~7pp with no material
performance cost. Without this, the strategy fails its own kill criterion #4 regardless of how
stable the holdings are.

### 7.2 Turnover is a design constraint, not only a kill criterion
Target annualized turnover **<= 45%**, hard ceiling **60%** (kill criterion #4). If projected
turnover at a rebalance exceeds 60% annualized, the rebalance must be **reduced to name changes
and constraint breaches only**, and the event logged. A kill criterion with no control mechanism
is a post-mortem, not a control.

## 8. Sell rules
S1 rank out of top 80 at two consecutive rebalances · S2 any §2.5 exclusion-level flag ·
S3 implied growth > 25% · S4 position > 12% (trim to 6%) or sector > 30% · S5 corporate action.
**Not** sell rules: price decline, a bad quarter, media narrative, boredom.

## 9. Calendar
Quarterly, 3rd Friday of Feb/May/Aug/Nov. Limit orders at midpoint, good-for-day, retried up to
3 sessions. Annual January review of the *strategy*, not the holdings.

## 10. Ablations — what must be measured
Full vs SPY/VTI/equal-weight · minus political · minus insider · minus institutional · minus
momentum · durability-only · valuation-only · **minus LLM features** · FF5+MOM regression ·
**after-tax vs pre-tax for every variant** · **factor IC for every component**.

## Change log
| Date | Change |
|---|---|
| 2026-08-03 | v1.0 initial |
| 2026-08-04 | v1.1 added DD + short interest to §2.5; institutional overlay §5.3; ablations |
| 2026-08-04 | v1.2 added factor IC to §10 (docs/13 §2.3) |
| 2026-08-04 | **v1.3** §7.1 no-trade band 3%; §7.2 turnover as a design constraint; §6 buffer rank 60→80. Driven by an end-to-end simulation in which the spec as written produced **99.6% annualized turnover**, failing its own kill criterion #4. Buffer rank chosen on the turnover constraint; the CAGR sweep was non-monotonic and no return benefit is claimed. |
