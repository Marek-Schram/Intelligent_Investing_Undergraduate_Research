# How Durable Alpha Works: Behind the Scenes

This document explains the technical details of how the investment system operates, without requiring deep financial expertise.

---

## Table of Contents

1. [The Core Investment Philosophy](#the-core-investment-philosophy)
2. [The Scoring System](#the-scoring-system)
3. [Data Pipeline](#data-pipeline)
4. [Portfolio Construction](#portfolio-construction)
5. [Risk Management](#risk-management)
6. [Tax Optimization](#tax-optimization)
7. [Backtesting & Validation](#backtesting--validation)
8. [The Discovery Sleeve](#the-discovery-sleeve)
9. [Execution Safeguards](#execution-safeguards)
10. [Research & Measurement](#research--measurement)

---

## The Core Investment Philosophy

### The Big Question
**Can a systematic, rules-based approach identify durable businesses trading at reasonable prices, and hold them long enough to beat a low-cost index fund after taxes and transaction costs?**

### The Hypothesis
Most investors:
- Trade too much (high costs)
- Sell winners too early (high taxes)
- Chase performance (buy high, sell low)
- Panic during downturns

A patient, rules-based system that:
- Focuses on business quality (not just price momentum)
- Holds for years (not months)
- Optimizes for after-tax returns
- Ignores short-term noise

...might do better, or at least match the market while teaching valuable skills.

### Why This Might Not Work
- **Small-cap premium** is mostly a historical artifact (1975-1983)
- **Value premium** has been weak for 15 years
- **Neglect premium** (under-followed stocks) is contested
- Transaction costs and taxes eat into returns
- Most active strategies underperform

### Why It Still Might Be Worth Trying
- **Tax alpha** (smart tax management) could add 0.5-1.5% annually
- Learning quantitative investing is valuable regardless of returns
- You're only risking 10% of your portfolio
- The infrastructure you build (data, backtesting, tax optimization) is reusable

---

## The Scoring System

### Overview
Every stock in the universe gets a score from 0-100 based on three categories:

| Category | Weight | What It Measures |
|----------|--------|------------------|
| **Durability** | 50% | Business quality and financial strength |
| **Valuation** | 35% | Is the price reasonable? |
| **Momentum** | 15% | Is the market starting to agree? |

### Durability (0-50 points)

This measures "is this a good business?" using several forensic checks:

#### 1. **Piotroski F-Score** (9 points max)
Nine binary tests of financial health:
- **Profitability:** Is net income positive? Is ROA increasing? Is operating cash flow > net income?
- **Leverage:** Is long-term debt decreasing? Is current ratio improving?
- **Operating efficiency:** Is gross margin improving? Is asset turnover improving?
- **Shares:** Is the company buying back shares (not diluting)?

A score of 8-9 = very healthy. A score of 0-3 = trouble.

#### 2. **ROIC Consistency** (10 points max)
**ROIC** = Return on Invested Capital (how efficiently the company uses money).

We calculate ROIC for the last 5 years and check:
- Is median ROIC > 12%? (Good businesses earn high returns)
- Is ROIC stable? (Consistency matters more than one great year)

**Why this matters:** A company with consistently high ROIC has a "moat" - something that protects it from competition (brand, patents, network effects, etc.).

#### 3. **Cash Conversion** (8 points max)
Does cash flow match earnings?

```
Accrual Ratio = (Net Income - Operating Cash Flow) / Total Assets
```

**Low accrual = good** (earnings are real cash, not accounting games)  
**High accrual = suspicious** (could be revenue manipulation)

#### 4. **Forensic Red Flags** (12 checks, any fail = 0 points)

These are warning signs from academic research on accounting fraud:
1. **Days Sales Outstanding (DSO) growing faster than revenue** - Are customers not paying?
2. **Inventory growing faster than COGS** - Is inventory piling up unsold?
3. **Asset quality declining** - Too many "soft" assets vs. real ones
4. **Sales growth vs. receivables growth** - Are sales real or just promises?
5. **Depreciation changes** - Artificially stretching asset life?
6. **Gross margin volatility** - Wild swings suggest problems
7. **SG&A leverage** - Are operating costs out of control?
8. **Effective tax rate anomalies** - Tax games?
9. **Free cash flow vs. net income gap** - Does cash match earnings?
10. **Merton Distance-to-Default** - Is bankruptcy a near-term risk?
11. **Short interest spikes** - Are informed traders betting against this?
12. **Credit spread widening** - Are bond markets worried?

If even ONE of these fires, the durability score drops to zero - **the company is excluded entirely**.

#### 5. **Earnings Quality** (10 points max)
How "real" are the earnings?

```
Earnings Quality = (Operating Cash Flow / Net Income)
```

A ratio > 1.0 is good (cash > accounting earnings).  
A ratio < 0.8 is concerning (where's the cash?).

### Valuation (0-35 points)

This measures "is the price reasonable?" using four methods:

#### 1. **EV/EBIT** (10 points max)
```
EV = Enterprise Value (market cap + debt - cash)
EBIT = Earnings Before Interest and Taxes
```

**Lower is better.** An EV/EBIT of 8 is cheaper than 20.

We exclude:
- Companies with negative EBIT (losing money)
- EV/EBIT > 50 (absurdly expensive)

#### 2. **Free Cash Flow Yield** (10 points max)
```
FCF Yield = (Free Cash Flow / Enterprise Value) × 100%
```

This is like a dividend yield, but for all the cash the company generates (not just what it pays out).

A 10% FCF yield is excellent. A 2% yield is expensive.

#### 3. **Shareholder Yield** (5 points max)
```
Shareholder Yield = (Dividends + Buybacks - Dilution) / Market Cap
```

This measures how much cash is being returned to shareholders.

**Why this matters:** Buybacks at low prices are great. Buybacks at high prices waste money. This metric captures both.

#### 4. **Reverse DCF Gap** (10 points max)

This is the most sophisticated valuation method. It asks:

**"What growth rate is already baked into this stock price?"**

We use a DCF (Discounted Cash Flow) model in reverse:
1. Take the current stock price as given
2. Solve for what growth rate would justify that price
3. Compare implied growth to historical growth

**Example:**
- Stock price implies 20% annual growth for 10 years
- But the company has historically grown at 5%
- **Gap = 15%** - the market is pricing in a miracle

**Large positive gap** = expensive (market expects too much)  
**Small or negative gap** = cheap (market is pessimistic)

We exclude companies where implied growth > 30% (too speculative).

### Momentum (0-15 points)

This measures "is the market starting to agree?"

#### 1. **12-1 Month Momentum** (10 points max)
```
Return from 12 months ago to 1 month ago (skipping the most recent month)
```

**Why skip the most recent month?** Research shows the last month often mean-reverts (bounces back), so we exclude it.

Positive momentum = the stock has been going up.

#### 2. **200-Day Trend** (5 points max)
```
Is the current price > 200-day moving average?
```

This is a simple long-term trend indicator.

### Tie-Breakers (Overlays)

If two stocks have the same score, we use these **capped** factors:

#### 1. **Insider Purchases** (max +2 points)
When executives buy their own company's stock (with their own money), it's a good sign.

**Logged separately** so we can test: *Do insider purchases actually predict returns?*

#### 2. **Congressional Trades** (max +1 point)
Members of Congress file STOCK Act disclosures within 45 days of trades.

**Logged separately** to test: *Do Congress members have an edge?*

#### 3. **13F Conviction** (max +2 points)
Large investment managers file "13F" reports quarterly, listing their holdings.

We look for:
- **Concentration**: Managers putting a large % of their portfolio in one stock
- **Consensus**: Multiple smart managers buying the same thing

**Logged separately** to test: *Do concentrated 13F positions predict returns?*

---

## Data Pipeline

### Where Data Comes From

| Data Type | Source | Update Frequency | Lag |
|-----------|--------|------------------|-----|
| Financial statements | SEC EDGAR | Quarterly | 0-45 days |
| Stock prices | Alpaca/Yahoo | Daily | 1 day |
| Short interest | FINRA | Twice monthly | 11+ business days |
| 13F filings | SEC | Quarterly | 45 days |
| STOCK Act | House/Senate | As filed | 45 days |
| Credit spreads | FRED | Daily | 1 day |
| Macro data | FRED | Monthly | Varies |

### Point-in-Time Database

**The most important technical detail:** All data is stored with an `available_at` timestamp.

When we query for "what was the universe on 2020-06-15?", the system returns **only information that actually existed on that date**.

#### Example:
- Company XYZ files a 10-Q on 2020-08-05
- We're backtesting as of 2020-08-01
- **That 10-Q does not exist yet** - it can't be used

This is called a **point-in-time (PIT) database**, and it's critical for honest backtesting.

### Survival Bias Prevention

**Problem:** Most financial databases quietly remove companies that went bankrupt or got delisted. This makes backtests look better than they should.

**Solution:** Our universe includes dead companies up until their delisting date.

When backtesting 2008, the system sees:
- Lehman Brothers (filed bankruptcy Sep 2008)
- Bear Stearns (acquired Mar 2008)
- Washington Mutual (seized Sep 2008)

If a value screen picked them, they're in the backtest - and the portfolio takes the loss.

### The Firewall

`firewall.py` is a second, independent check against look-ahead bias.

It asserts:
- All dates in the query are <= `as_of` date
- No adjusted-close price series (they're retroactively restated)
- Filing dates match SEC acceptance timestamps
- No data with `available_at` in the future

If you accidentally write code that peeks into the future, **the firewall throws an error**.

---

## Portfolio Construction

### Step 1: Build the Universe

Start with all US-listed stocks, then filter:

| Filter | Threshold | Why |
|--------|-----------|-----|
| Market cap | ≥ $100M | Too small = illiquid |
| Avg daily volume | ≥ $1M | Need to be able to trade |
| Price | ≥ $5 | Avoid penny stocks |
| Exclude | Financials | Different accounting |
| Exclude | OTC, Pink Sheets | Too risky |

**Result:** ~2,500 stocks

### Step 2: Score Everything

Calculate durability, valuation, and momentum for all 2,500 stocks.

### Step 3: Rank and Select

- Sort by total score (high to low)
- **Selection buffer:** Buy if rank ≤ 60, hold if rank ≤ 70
  - This creates a "buffer zone" to reduce turnover
  - A stock ranked 65 is held (don't sell), but new money goes to stocks ranked 1-60

### Step 4: Position Sizing

Start with equal weight:
```
Target weight = 1 / N (where N = number of holdings)
```

**Example:** 20 stocks = 5% each

Then apply rebalancing bands:
- **Don't rebalance** if current weight is within ± 2% of target
- This reduces trading (and taxes)

### Step 5: Generate Proposal

The system creates a list:
```
BUY: AAPL, 150 shares @ limit $180.50
SELL: IBM, 200 shares @ limit $140.25
```

**Human reviews and approves** - the system never trades automatically.

---

## Risk Management

### Position Limits
- No single stock > 8% of the portfolio (after rebalancing)
- Min holding period: 12 months (unless a sell rule fires)
- Max 25 positions (maintains diversification)

### Sell Rules (C1-C5)

You sell a stock **only if** one of these five rules triggers:

#### C1: Durability Collapse
```
Durability score < 50 for two consecutive quarters
```
The business quality has declined significantly.

#### C2: Valuation Blowout
```
Composite valuation score < 10 (extremely expensive)
AND
Price has risen > 100% since purchase
```
Don't sell just because it's expensive - but if it's **extremely** expensive and you have a large gain, take profits.

#### C3: Manipulation Flag
```
Any forensic red flag fires
```
Signs of fraud or distress - exit immediately.

#### C4: Accounting Quality Break
```
Accrual ratio > 0.10 (high)
AND
Earnings quality < 0.6 (low cash conversion)
```
Earnings might be fake.

#### C5: Liquidity Dry-Up
```
90-day avg daily volume < $500K
```
Can't get out if you need to.

**Note:** Price decline is NOT a sell rule. We expect volatility.

### Discovery Sleeve (Sleeve E) Limits

The high-risk small-cap strategy has strict constraints:
- Max 2% of total portfolio
- Max 8 positions
- Max 0.25% per position
- Staged entry: 40% / 30% / 30% tranches, 90 days apart
- **Cannot be increased** based on good performance (prevents risk creep)

### Speculation Limits

No:
- Leverage
- Margin
- Shorting
- Options
- Crypto
- Penny stocks (< $5)

---

## Tax Optimization

### Lot Tracking

Every share purchase is tracked separately:
```
Bought 100 AAPL @ $150 on 2024-01-15 (Lot #1)
Bought 50 AAPL @ $160 on 2024-06-20 (Lot #2)
```

When you sell, you can choose **which lot** to sell from.

### Tax-Loss Harvesting

If a stock is down, selling it creates a tax loss that offsets gains elsewhere.

**The algorithm:**
1. Identify positions with unrealized losses
2. Check if selling now saves taxes vs. carrying the loss forward
3. Avoid wash sales (can't buy back within 30 days)
4. Propose sales that maximize after-tax value

### Lot Selection Method

When selling, the system picks lots to minimize taxes:

**Highest-In-First-Out (HIFO) with long-term preference**
1. Prefer lots held > 12 months (long-term capital gains rate is lower)
2. Within long-term lots, sell highest-cost-basis first (minimizes gain)
3. Within short-term lots, sell highest-cost-basis first

**Example:**
You need to sell 100 shares of AAPL:
- Lot A: 50 shares @ $150, held 18 months → sell these (long-term, high basis)
- Lot B: 75 shares @ $140, held 18 months → sell 50 of these (long-term, high basis)
- Lot C: 100 shares @ $170, held 6 months → don't touch (short-term, trigger high tax)

### Wash Sale Detection

**Problem:** If you sell a stock for a loss, then buy it back within 30 days, the IRS "disallows" the loss (you can't claim it on taxes yet).

**Solution:** The system tracks:
- All sales in the last 30 days
- All purchases in the next 30 days
- Flags wash sales
- Adjusts cost basis accordingly

It even checks **across accounts** (taxable + IRA) to catch hidden wash sales.

### Tax Alpha Measurement

```
Tax Alpha = After-Tax Return (Optimal) - After-Tax Return (FIFO)
```

This measures how much value the smart lot selection adds vs. just selling oldest shares first.

Target: 0.5-1.5% per year (this alone might justify the entire system).

---

## Backtesting & Validation

### Walk-Forward Testing

We don't train on all historical data at once. Instead:

1. Train on 2015-2018 data
2. Test on 2019 (out-of-sample)
3. Train on 2015-2019 data
4. Test on 2020 (out-of-sample)
5. Repeat...

This simulates how the system would actually be used in real time.

### Combinatorial Purged Cross-Validation (CPCV)

**The Problem:** Standard backtesting can overfit. You might find a strategy that worked in the past by luck.

**The Solution:** Run 120 different train/test splits:
1. Split the 10-year period into chunks
2. Train on different combinations of chunks
3. Test on the held-out chunks
4. Measure how consistent results are

**Purging:** Make sure training and test sets don't overlap (important for time-series data).

**Embargo:** Add a buffer between train and test periods (prevents information leakage).

**Output:** Probability of Backtest Overfitting (PBO)
- PBO < 0.5 = strategy is likely robust
- PBO > 0.5 = strategy is likely overfit (kill criterion)

### Factor Information Coefficient (IC)

**The Question:** Is the signal itself any good, or does the portfolio just look fine because of how we build it?

**The Test:**
1. At each rebalance date, rank all stocks by their factor score
2. One month later, rank all stocks by their actual return
3. Calculate the correlation (Spearman rank IC)

**Interpretation:**
- IC > 0.05 = decent signal
- IC > 0.10 = strong signal
- IC < 0.02 = weak/noise

**Why this matters:** A portfolio backtest can look good due to:
- Luck
- Survivor bias
- Good risk management

But IC tests the **signal itself**, independent of portfolio construction.

### Market Impact Modeling

**Almgren-Chriss Model:**

When you trade, you move the market:
- **Permanent impact:** Price moves permanently (you're revealing information)
- **Temporary impact:** Price moves while you trade, then recovers (liquidity cost)

The model calculates:
```
Expected cost = f(size, volatility, spread, volume)
```

We include this in backtest returns - no "free" trades at the closing price.

### Contamination Test

**The Problem:** If you use an LLM to analyze earnings calls, and the model was trained after your test period, **it has read the future**.

**The Solution:** 
1. Split backtest into pre-cutoff and post-cutoff periods
2. Measure performance in each
3. If post-cutoff performance is much worse, the signal is contaminated

**Claude's training cutoff:** May 2025  
**Our test:** Performance before vs. after May 2025

---

## The Discovery Sleeve

### The Idea

Small, under-followed companies might be mispriced because:
- No analyst coverage
- Institutions can't own them (too small)
- Retail investors don't know they exist

### The Process

#### Step 1: Screen for Neglect
- Market cap: $100M - $500M
- Analyst coverage: ≤ 2 analysts
- 13F filers: ≤ 10 institutions
- Industry neglect: Industry has < 5% of market attention

#### Step 2: Manipulation Gate

**This is the critical step:** Before even scoring, check for fraud flags.

If **any one** of these is true, **reject immediately**:
1. Merton distance-to-default < 2.0 (bankruptcy risk)
2. Short interest > 20% of float (red flag)
3. Credit spread > 800bps (market smells trouble)
4. DSO or inventory growth > 2× revenue growth
5. Gross margin volatility > 30%
6. Effective tax rate < 5% or > 40% (tax games)
7. Asset quality < 0.5 (soft assets)
8. Accrual ratio > 0.15 (suspicious earnings)

**No second chances.** One flag = excluded entirely.

#### Step 3: Score Survivors

Use the same durability + valuation system as Sleeve C.

#### Step 4: Staged Entry

Don't buy the full position at once:
- **Tranche 1:** 40% of target weight (day 0)
- **Tranche 2:** 30% of target weight (day 90) *if no manipulation flags*
- **Tranche 3:** 30% of target weight (day 180) *if no manipulation flags*

This allows you to exit early if red flags appear before committing full capital.

#### Step 5: Dossier (Due Diligence)

For each candidate, generate a 9-section dossier:
1. Business model in plain English
2. Competitive position
3. Financial health summary
4. Why is this neglected? (industry, coverage, boring business)
5. Valuation: what's cheap here?
6. Red flags (even minor ones)
7. Liquidity and trading mechanics
8. Tax implications (any weird structure?)
9. Hold/sell logic

**Human reads this before approving the position.**

### Exit Rules (E1-E5)

Tighter than Sleeve C (because these are riskier):

- **E1:** Never held for < 12 months (tax)
- **E2:** Durability < 55 for two consecutive quarters (higher bar than C1)
- **E3:** Score falls out of top 8 AND below rank 20
- **E4:** Any manipulation flag fires (immediate exit, regardless of P&L)
- **E5:** Liquidity < $500K/day (can't exit safely)

---

## Execution Safeguards

### Multi-Layer Safety

#### Layer 1: Configuration Flags
```yaml
live_trading_approved: false  # Human-only toggle
max_order_value: 10000        # Per-order limit
```

A **hook blocks Claude from editing these**. The human must manually change the config file.

#### Layer 2: Proposal/Submit Split

```bash
make propose AS_OF=2024-08-01  # Generate trades (no execution)
# Human reviews output
make submit                     # Execute approved trades
```

Two separate commands - you must consciously decide to submit.

#### Layer 3: Dry-Run Default

```python
def submit_order(ticker, qty, dry_run=True):
    if dry_run:
        return simulate_order(ticker, qty)
    else:
        return alpaca.submit_order(ticker, qty)
```

Every execution function defaults to `dry_run=True`. You must explicitly pass `False`.

#### Layer 4: Pre-Trade Assertions

Before any trade:
```python
assert config['live_trading_approved'] is True
assert broker_url == PAPER_URL or reconcile_passed()
assert order_value <= config['max_order_value']
assert ticker in approved_universe
```

#### Layer 5: Reconciliation

Before any live order:
```python
assert portfolio_db matches broker_api
```

If your internal ledger doesn't match the broker, **trading is blocked** until you fix it.

### Proposal Format

```
=== PROPOSAL 2024-08-01 ===

BUY ORDERS:
  AAPL: 100 shares @ limit $180.50 (= $18,050)
    Reason: Entered top 60, rank 45
    Score: D=42, V=28, M=12 → 82
    
SELL ORDERS:
  IBM: 150 shares @ limit $140.00 (= $21,000)
    Reason: Durability < 50 for 2Q (rule C1)
    Lots: [Lot #45: 100sh @ $150 (LT), Lot #52: 50sh @ $148 (LT)]
    Expected gain: $-1,500 ST, $0 LT
    Tax impact: $0 (loss)

HOLD (no action):
  [22 other positions]

Total capital deployed: $18,050
Total capital freed: $21,000
Net cash change: +$2,950
Projected turnover: 8% (annualized)
```

**You read this, understand each trade, and then decide whether to submit.**

---

## Research & Measurement

### Preregistration

Before running any backtest, you write down:
1. What you expect to happen
2. Why you expect it
3. How you'll measure it
4. What would count as success vs. failure

This prevents "p-hacking" (trying 100 things and only reporting what worked).

### The Seven Hypotheses

**H1:** The composite durability score predicts positive excess returns over 1-3 years.  
**H2:** The neglect premium (Sleeve E) adds value after the manipulation gate.  
**H3:** Insider purchases add predictive power as a tie-breaker.  
**H4:** Tax alpha from lot selection exceeds any selection alpha.  
**H5:** The forensic red flags reduce tail risk (avoid blowups).  
**H6:** CPCV-validated strategies have lower PBO than walk-forward alone.  
**H7:** Factor IC decay across model cutoff indicates contamination.

### Claims Ledger

Every claim you make gets logged:
```
Claim #23:
  Date: 2024-08-01
  Claim: "The durability score will have IC > 0.05 in 2024-2025"
  Evidence: IC = 0.032 (measured 2025-12-31)
  Status: Contradicted
  Contradicted by: claim_23_result.csv
```

Over time, you learn what you're good at predicting and what you're not.

### Decision Journal

Every time you make a decision:
```
Decision #15:
  Date: 2024-08-01
  Question: Should I increase Sleeve E to 5% after good performance?
  Prediction: 70% confident this will improve returns
  Reasoning: The system is working; I should scale it up
  Decision: NO (hard limit prevents this)
  Outcome: [TBD in 2025-08-01]
  Calibration: [TBD]
```

After one year, you can measure: **When you were 70% confident, were you right 70% of the time?**

This is called **calibration**, and it's the most important skill in investing.

### Research Export

At any point, you can run:
```bash
make research-export
```

This generates:
- Returns series (daily, monthly, annual)
- Factor IC time series
- Trade log with reasons
- Tax impact summary
- Calibration scores
- Claims ledger
- All the data needed to write a paper

The output is designed for:
- LaTeX (academic paper)
- Excel (personal review)
- Jupyter notebooks (further analysis)

---

## How the Pieces Fit Together

```
┌─────────────────────────────────────────────────────────────────┐
│                         DATA INGESTION                           │
│  SEC EDGAR → Financial statements (10-K, 10-Q) → Point-in-time  │
│  FINRA → Short interest → Lag 11+ days                           │
│  Alpaca → Prices (unadjusted + split/dividend events) → Lag 1d  │
│  13F filings → Institutional positions → Lag 45d                 │
│                                                                   │
│  ↓ All stored in DuckDB with available_at timestamps             │
└─────────────────────────────────────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│                         FIREWALL CHECK                           │
│  Assert: No future data, no adjusted-close series, lags correct │
└─────────────────────────────────────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│                      FACTOR CALCULATION                          │
│  Durability: F-Score + ROIC + forensics + cash quality          │
│  Valuation: EV/EBIT + FCF yield + shareholder yield + DCF       │
│  Momentum: 12-1 month + 200d MA                                  │
│  Overlays: Insider + Congress + 13F (capped, logged)            │
└─────────────────────────────────────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│                      PORTFOLIO CONSTRUCTION                      │
│  Rank by composite score → Top 60 buy, hold if ≤70              │
│  Equal weight + rebalancing bands (±2%)                          │
│  Check sell rules C1-C5 → Generate proposal                      │
└─────────────────────────────────────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│                         HUMAN REVIEW                             │
│  Read proposal → Understand each trade → Approve or reject       │
└─────────────────────────────────────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│                          TAX OPTIMIZATION                         │
│  Select lots: HIFO with LT preference                            │
│  Check for wash sales (30-day window, cross-account)            │
│  Harvest losses if beneficial                                    │
└─────────────────────────────────────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│                          EXECUTION                               │
│  Assert: live_trading_approved, reconciliation passes            │
│  Submit limit orders via Alpaca API                              │
│  Log everything (time, price, lot IDs, reason)                   │
└─────────────────────────────────────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────┐
│                          REPORTING                               │
│  Calculate returns (pre-tax, after-tax)                          │
│  Attribution: What drove performance?                            │
│  Risk metrics: Sharpe, max drawdown, volatility                  │
│  Tax alpha: Optimal vs. FIFO                                     │
│  Factor IC: Is the signal itself good?                           │
│  Calibration: Were predictions accurate?                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key Insights & Design Decisions

### 1. Why Not Machine Learning?

**We don't use ML for prediction because:**
- ML models trained after the test period have "seen the future"
- Reported LLM trading results often collapse under longer evaluation
- Interpretability matters for a personal portfolio
- Overfitting is too easy with high-dimensional data

**We DO use LLMs for extraction:**
- Pulling specific facts from 10-Ks (with citations required)
- Summarizing business models for the dossier
- Contamination testing measures if this hurts us

### 2. Why Hold for Years?

**Short-term trading is hard:**
- High turnover = high taxes (30-40% short-term rate)
- High turnover = high transaction costs
- Competition at short horizons is fierce (HFT, quants)

**Long-term holding is easier:**
- Lower taxes (15-20% long-term rate)
- Lower costs (fewer trades)
- Less competition (many funds have monthly/quarterly horizons)
- Tax loss harvesting has more opportunities

### 3. Why the Buffer Zone?

Without a buffer:
- Stock ranks 61 → sell
- Next quarter ranks 59 → buy back
- This creates "thrashing" (unnecessary trades)

With a buffer (buy ≤ 60, hold ≤ 70):
- Stock ranks 61 → hold
- Stock ranks 65 → still hold
- Stock ranks 75 → sell
- Turnover drops from 40%/year to 15%/year

### 4. Why Staged Tranches for Sleeve E?

Small-cap fraud is real:
- 40% upfront: Test the waters
- 30% at 90 days: Business confirmation (no red flags)
- 30% at 180 days: Further confirmation

If a manipulation flag fires, you've only deployed 40% or 70% of capital - you can exit before full damage.

### 5. Why Separate Execution from Research?

**Principle:** Code that can place trades must never be imported by code that generates reports.

**Why:** If reporting code can execute trades, a bug could accidentally submit orders. Or worse, an AI agent hallucinating could trigger trades.

**Enforcement:** 
- Directory structure separates `execution/` from `reporting/`
- Tests assert no import paths cross this boundary
- Hooks block dangerous imports

### 6. Why Test Against Dead Companies?

**If you exclude failed companies:**
- Every value screen looks better (you're hiding the losers)
- Risk metrics are too optimistic
- You're measuring "how good was I at picking survivors?" not "how good is this strategy?"

**By including them:**
- 2008 backtest shows Lehman, Bear, WaMu losses
- Returns are honest
- Risk is properly measured

### 7. Why the Forensic Red Flags?

These 12 checks come from academic research on accounting fraud (Beneish, Sloan, Piotroski, Altman).

**Key insight:** One flag might be noise. But if ANY ONE flag fires, the odds of a serious problem are high enough to just avoid the stock entirely.

**Think of it like medical screening:**
- You don't wait for 5 symptoms to see a doctor
- One serious symptom is enough
- Same logic here

---

## What Could Go Wrong?

### Strategy Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Small-cap premium doesn't exist | High | Medium | Only 2% in Sleeve E |
| Value premium stays weak | Medium | Medium | Momentum overlay + only 10% total |
| Transaction costs exceed alpha | Medium | Medium | Turnover bands, limit orders |
| Tax law changes | Low | High | Doesn't invalidate fundamentals |
| Accounting fraud slips through | Low | High | 12 forensic checks, diversification |

### Operational Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Data feed error | Medium | High | Firewall assertions, reconciliation |
| Accidental live trade | Low | Severe | Hooks, dry-run defaults, multi-layer checks |
| Backtest look-ahead | Medium | Severe | Firewall + manual audits |
| Code bug in tax logic | Medium | High | 787 tests, CPA review of generated tax forms |
| API rate limit hit | High | Low | Retry logic, caching |

### Market Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Market crash | High (eventually) | High | Only 10% in active strategy, diversified index funds |
| Liquidity crisis | Medium | Medium | Hold long-term, don't panic sell |
| Flash crash during execution | Low | Medium | Limit orders (not market orders) |
| Broker failure | Very low | Severe | SIPC insurance, use major broker |

---

## Performance Expectations

### Realistic Scenarios

**Optimistic (30% probability):**
- Strategy beats S&P 500 by 2-3% annually
- Tax alpha adds another 1%
- Total outperformance: 3-4% on the 10% sleeve
- Portfolio impact: +0.3-0.4% per year

**Base case (50% probability):**
- Strategy roughly matches S&P 500 (± 1%)
- Tax alpha adds 0.75%
- Total: slight outperformance
- Portfolio impact: +0.1% per year

**Pessimistic (20% probability):**
- Strategy underperforms by 2-3% annually
- Tax alpha adds 0.5%
- Total: slight underperformance
- Portfolio impact: -0.2% per year

**Important:** Even in the pessimistic case, the 90% in index funds means total portfolio is fine.

### What About Sleeve E?

**If the neglect premium is real:** +5-8% annually (but only 2% of portfolio)  
**If it's not:** -2-4% annually (survivorship bias in research)  
**Portfolio impact:** ± 0.1-0.15% per year

The discovery sleeve is an expensive research project. You're paying tuition to learn if neglect matters.

---

## Measuring Success

### Year 1
- **Strategy:** Do the factors have positive IC?
- **Tax:** Is tax alpha > 0.5%?
- **Research:** Are you well-calibrated on predictions?

### Years 2-3
- **Strategy:** Is walk-forward return > 0 after costs?
- **Tax:** Is HIFO beating FIFO consistently?
- **Discovery:** Did any Sleeve E names work out?

### Years 5-10
- **Strategy:** Is total return competitive with S&P 500?
- **Tax:** Has cumulative tax alpha compounded meaningfully?
- **Learning:** Do you understand markets better than when you started?

### The Meta-Goal
Even if the strategy fails financially, you will have:
- Built a reusable quantitative research framework
- Learned financial statement analysis
- Practiced disciplined decision-making
- Measured your own calibration
- Created a point-in-time database
- Written backtesting infrastructure
- Understood tax optimization

**These skills transfer to actuarial work, quant finance, and any analytical career.**

---

## Further Reading

### In This Repo
- `docs/00_STRATEGY_SPEC.md` - Full technical specification
- `docs/03_BACKTEST_PROTOCOL.md` - Validation methodology
- `docs/11_TAX_ENGINE.md` - Tax optimization details
- `docs/13_OPEN_SOURCE_AUDIT.md` - What we rejected and why

### Academic Papers
- Piotroski (2000) - F-Score
- Sloan (1996) - Accruals and earnings quality
- Beneish (1999) - M-Score (manipulation detection)
- Jegadeesh & Titman (1993) - Momentum
- Frazzini et al. (2018) - Tax-loss harvesting value

### Books
- *The Intelligent Investor* (Graham) - Value investing philosophy
- *Quality Investing* (O'Shaughnessy) - Forensic accounting
- *Active Portfolio Management* (Grinold & Kahn) - Information coefficient
- *Expected Returns* (Ilmanen) - What works and what doesn't

---

## Questions?

If something in this document is unclear, check:
1. The source code (it's commented)
2. The test files (they show examples)
3. The `docs/` folder (more technical depth)
4. The CLAUDE.md (working context for the AI)

And remember: **the goal is to learn, not to get rich**. If you come out of this with:
- A well-tested backtesting framework
- An understanding of financial statements
- Good calibration on your predictions
- A 0.5% annual tax alpha

...you've won, even if the stock picks don't beat the market.

---

*This project is for educational and personal research. Not investment advice. Verify everything.*
