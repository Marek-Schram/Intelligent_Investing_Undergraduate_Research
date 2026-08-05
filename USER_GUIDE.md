# Durable Alpha: Complete User Guide

**Version:** 1.0  
**Last Updated:** August 2026  
**Status:** Paper trading ready, live trading requires manual approval

---

## Table of Contents

1. [First-Time Setup](#first-time-setup)
2. [Daily/Weekly Workflow](#dailyweekly-workflow)
3. [Quarterly Rebalancing](#quarterly-rebalancing)
4. [Working with Claude Code](#working-with-claude-code)
5. [Command Reference](#command-reference)
6. [Understanding Output](#understanding-output)
7. [Troubleshooting](#troubleshooting)
8. [Going Live (Real Money)](#going-live-real-money)
9. [Maintenance & Updates](#maintenance--updates)
10. [Advanced Usage](#advanced-usage)

---

## First-Time Setup

### Prerequisites

Before you start, make sure you have:
- Python 3.12 installed
- Git installed
- A terminal/command line
- 30-60 minutes for initial setup

### Step 1: Get API Keys (All Free)

#### 1.1 SEC EDGAR Identity
You need to provide an email so the SEC knows who's downloading data.

**Action:** You'll add this to your `.env` file as:
```
SEC_USER_AGENT=Your Name <your.email@example.com>
```

#### 1.2 Alpaca Paper Trading Account
This gives you fake money to test with.

1. Go to https://alpaca.markets
2. Sign up for a free account
3. Go to "Paper Trading" section
4. Copy your **API Key** and **Secret Key**

**Action:** Add to `.env` file:
```
ALPACA_API_KEY=your_key_here
ALPACA_SECRET_KEY=your_secret_here
ALPACA_BASE_URL=https://paper-api.alpaca.markets
```

#### 1.3 FRED API (Federal Reserve Economic Data)
This provides interest rate data.

1. Go to https://fred.stlouisfed.org/docs/api/api_key.html
2. Create a free account
3. Request an API key (instant approval)

**Action:** Add to `.env` file:
```
FRED_API_KEY=your_fred_key_here
```

### Step 2: Install Dependencies

Open your terminal and navigate to the project:

```bash
cd "/home/msz4y/claudeCode/Investing with Claude/durable-alpha"
```

Install everything:
```bash
uv sync
```

This will:
- Create a virtual environment (`.venv/`)
- Install all Python packages
- Take about 2-5 minutes

### Step 3: Configure Your Settings

#### 3.1 Copy example files
```bash
cp .env.example .env
cp config/config.example.yaml config/config.yaml
```

#### 3.2 Edit `.env` with your API keys
```bash
# Use any text editor (nano, vim, VS Code, etc.)
nano .env
```

Add your API keys from Step 1.

**IMPORTANT:** Never commit `.env` to git - it's already in `.gitignore`.

#### 3.3 Edit `config/config.yaml`
```bash
nano config/config.yaml
```

Key settings to check:
```yaml
# Portfolio settings
portfolio:
  total_capital: 100000  # Your total portfolio size (all sleeves)
  sleeve_c_pct: 0.08     # Durability sleeve: 8% of total
  sleeve_e_pct: 0.02     # Discovery sleeve: 2% of total
  target_positions_c: 20  # Number of stocks in sleeve C
  target_positions_e: 8   # Max positions in sleeve E

# Safety (DO NOT CHANGE until you're ready for real trading)
execution:
  live_trading_approved: false  # MUST be false for paper trading
  dry_run_default: true
  max_order_value: 10000  # Max $ per order (safety limit)

# Tax settings (adjust for your situation)
tax:
  short_term_rate: 0.32  # Your short-term capital gains tax rate
  long_term_rate: 0.15   # Your long-term capital gains tax rate
  state_rate: 0.05       # Your state tax rate (if applicable)
```

### Step 4: Verify Installation

Run the test suite:
```bash
make test
```

**Expected output:**
```
=============== 787 passed, 35 xfailed, 29 warnings in ~36s ================
```

- **787 passed**: Core functionality works ✅
- **35 xfailed**: Expected failures (future features, documented in tests)
- **29 warnings**: Deprecation warnings (no action needed)

If tests pass, you're ready to go!

### Step 5: Initial Data Ingestion

Download historical data:
```bash
make ingest
```

This will:
- Download price data from Alpaca
- Download macro data from FRED
- Take 5-15 minutes depending on your internet

**Note:** SEC filings are downloaded on-demand (when you score stocks).

---

## Daily/Weekly Workflow

### What You Should Do Daily (5 minutes)

**Nothing!** This is a long-term system. Daily checking can lead to overtrading.

### What You Should Do Weekly (15 minutes)

**Check for system updates:**
```bash
# Pull latest code (if working with updates)
git pull

# Re-run tests to ensure nothing broke
make test
```

**Review your portfolio:**
```bash
make report TYPE=portfolio
```

This shows:
- Current positions
- Unrealized gains/losses
- Weight drift from targets
- Any approaching sell signals

**What NOT to do:**
- Don't panic over weekly price movements
- Don't adjust the strategy based on short-term performance
- Don't check individual stock prices obsessively

---

## Quarterly Rebalancing

**Do this once every 3 months** (or when you want to rebalance).

### Pre-Rebalancing Checklist

Before generating proposals, verify:
- [ ] Tests are passing (`make test`)
- [ ] Data is up-to-date (`make ingest`)
- [ ] You've reviewed recent positions (`make report TYPE=portfolio`)
- [ ] You understand any recent changes to holdings
- [ ] You have time to review proposals carefully (1-2 hours)

### Step 1: Update Data

```bash
make ingest
```

Make sure you have the latest prices and economic data.

### Step 2: Score the Universe

```bash
make score AS_OF=$(date +%Y-%m-%d)
```

**Example:**
```bash
make score AS_OF=2026-08-05
```

**Output:** CSV file with all stocks ranked by score.

**What to review:**
- Top 60 stocks (eligible for purchase)
- Ranks 61-70 (buffer zone - held but not bought)
- Your current holdings' ranks
- Any red flags (exclusions)

**File location:** `reports/scores_2026-08-05.csv`

### Step 3: Generate Proposals

```bash
make propose AS_OF=$(date +%Y-%m-%d)
```

**This does NOT execute trades** - it only creates a proposal.

**Output:** A detailed proposal showing:
- What to BUY (ticker, shares, price, reason)
- What to SELL (ticker, shares, price, reason, tax impact)
- What to HOLD (no action)
- Expected turnover
- Tax consequences
- Total capital moves

**File location:** `reports/proposal_2026-08-05.json` and `.txt`

### Step 4: Review Each Proposed Trade

**For each BUY, ask yourself:**
1. Why is this stock scoring well? (Check the scores CSV)
2. Do I understand the business? (Look up the company)
3. Is the price reasonable? (Check current market price vs. proposal limit)
4. Does this fit my portfolio? (Sector concentration, etc.)

**For each SELL, ask yourself:**
1. Which sell rule fired? (C1-C5)
2. Is the reason valid? (Not just "price went down")
3. What are the tax implications? (Short-term vs. long-term)
4. Am I comfortable with this decision?

**RED FLAGS to watch for:**
- Selling a long-term winner just because it got expensive (C2 requires 100% gain)
- Buying something you don't understand
- Excessive turnover (> 40% annually)
- Large tax hit for unclear benefit

### Step 5: Manual Research (Critical!)

**For each new position proposed, do 15 minutes of research:**

```bash
# Generate a dossier for a specific ticker
make dossier TICKER=AAPL
```

This creates a 9-section report:
1. Business model in plain English
2. Competitive position
3. Financial health
4. Why is this neglected? (if applicable)
5. Valuation rationale
6. Red flags
7. Liquidity and trading
8. Tax implications
9. Hold/sell logic

**Read this before approving the purchase.**

You can also manually check:
- Company's latest 10-K (annual report)
- Recent news (Google News)
- Seeking Alpha or similar for opinions (be skeptical)
- Insider transactions (Form 4 filings)

### Step 6: Modify Proposals (If Needed)

If you want to skip a trade:

**Option A: Edit the proposal file directly**
```bash
nano reports/proposal_2026-08-05.json
```

Remove the trade you don't want, or change the quantity.

**Option B: Regenerate with exclusions**

If you want to permanently exclude a ticker:
```bash
# Edit config to add to exclusion list
nano config/config.yaml

# Add under exclusions:
exclusions:
  tickers:
    - "TICKER1"
    - "TICKER2"
  reason: "Personal preference / ethical / other reason"
```

Then regenerate the proposal.

### Step 7: Execute Trades

**When you're 100% comfortable with the proposal:**

```bash
make submit
```

**This will:**
1. Re-validate all constraints
2. Check for a KILL file (emergency stop)
3. Verify you're in paper mode (or have approved live trading)
4. Place limit orders with your broker
5. Log every trade

**Expected time:** 2-5 minutes (broker processing)

**Output:**
```
=== EXECUTION SUMMARY ===
Submitted 3 buy orders
Submitted 2 sell orders
Total capital deployed: $42,500
All orders logged to reports/execution_log.csv
```

### Step 8: Verify Execution

Check that orders filled:

```bash
# If using Alpaca, check via their web interface
# Or query via the broker module
make reconcile
```

This compares your internal ledger to the broker's records.

**If there's a mismatch:** STOP and investigate before any further trading.

### Step 9: Update Your Records

Generate a post-trade report:

```bash
make report TYPE=quarterly
```

This creates a comprehensive report with:
- Pre/post rebalancing snapshots
- Trades executed and why
- Tax impact summary
- Portfolio attribution
- Performance vs. benchmarks

**File location:** `reports/quarterly_2026-Q3.pdf`

### Step 10: Log Your Decision

Update your decision journal:

```bash
make journal
```

Answer the prompts:
- What did you decide?
- What did you predict would happen?
- How confident were you?

**Why this matters:** In 6-12 months, you'll score your calibration - "when you were 80% confident, were you right 80% of the time?"

---

## Working with Claude Code

### What is Claude Code?

Claude Code is an AI assistant (me!) that can help you:
- Run commands
- Interpret results
- Debug issues
- Explain financial concepts
- Review code
- Generate reports

### How to Use Claude Code

#### Starting a Session

From the project directory:
```bash
claude
```

This opens an interactive session where you can ask questions.

#### Example Queries

**"Explain the durability score"**
I'll read the code and docs, then explain in plain English.

**"Why did AAPL get excluded from the last scoring run?"**
I'll check the scores file and trace through the logic.

**"Generate a backtest from 2020-2024"**
I'll run `make backtest SEGMENT=2020-2024` and interpret the results.

**"What would happen if I increased Sleeve E to 5%?"**
I'll explain the risk implications and policy reasons for the 2% cap.

**"Fix the failing test"**
I'll run the tests, diagnose the issue, and propose a fix.

#### Best Practices with Claude Code

**DO:**
- Ask "why" questions about code or strategy
- Request explanations of results
- Ask for help debugging
- Have me generate reports or visualizations
- Ask about risk or tax implications

**DON'T:**
- Ask me to bypass safety limits without understanding why they exist
- Expect me to predict stock prices (I won't and can't)
- Ask me to enable live trading (human-only decision)
- Assume I remember past conversations (check memory docs if needed)

#### Key Files I Reference

When you ask questions, I automatically check:
- `CLAUDE.md` - My instruction manual for this project
- `.claude/rules/` - Hard constraints I must follow
- `docs/` - Detailed technical documentation
- `tests/` - Test files showing how things work
- Recent `reports/` - Your actual results

#### Claude Code Limitations

**I cannot:**
- Access the internet (except via configured MCP tools)
- Predict future stock prices
- Give personalized financial advice
- Modify safety-critical configs (hooks block me)
- Execute live trades without your explicit approval

**I can:**
- Run any command you could run manually
- Read and explain any code or data file
- Generate reports and visualizations
- Help you understand results
- Debug issues
- Suggest improvements to code (but you review)

---

## Command Reference

### Data Management

```bash
# Download/update all data sources
make ingest

# Ingest specific data type
make ingest-prices
make ingest-fundamentals
make ingest-macro

# Check data coverage
make data-status
```

### Scoring & Ranking

```bash
# Score all stocks as of a date
make score AS_OF=2026-08-05

# Score with custom config
make score AS_OF=2026-08-05 CONFIG=config/custom.yaml

# Export scores to CSV for analysis
# (Output automatically goes to reports/scores_YYYY-MM-DD.csv)
```

### Portfolio Management

```bash
# Generate trade proposal (does NOT execute)
make propose AS_OF=2026-08-05

# Execute the proposal (after review!)
make submit

# Reconcile internal ledger with broker
make reconcile

# View current portfolio
make report TYPE=portfolio
```

### Backtesting & Validation

```bash
# Run walk-forward backtest
make backtest SEGMENT=2020-2024

# Run CPCV (combinatorial purged cross-validation)
make cpcv

# Calculate factor information coefficient
make ic FACTOR=durability
make ic FACTOR=valuation
make ic FACTOR=momentum

# Run all ablations (test what matters)
make ablations
```

### Discovery Sleeve (Sleeve E)

```bash
# Screen for neglected small caps
make discover AS_OF=2026-08-05

# Generate detailed dossier for a candidate
make dossier TICKER=SMCI

# Check tranche graduation status
make tranche-status
```

### Tax & Reporting

```bash
# Generate performance report
make report TYPE=monthly
make report TYPE=quarterly
make report TYPE=annual

# Tax review (harvest opportunities, wash sales)
make tax-review

# Export for tax prep
make tax-export YEAR=2025

# Calculate tax alpha vs. FIFO
make tax-alpha
```

### Research & Analysis

```bash
# Export data for external analysis
make research-export

# Update decision journal
make journal

# Check calibration scores
make calibration

# Run leakage audit
make leakage-audit
```

### Maintenance

```bash
# Run all tests
make test

# Run specific test file
pytest tests/test_durability.py -v

# Lint/format code
make lint
make format

# Clean temporary files
make clean
```

### Reproduction & Auditing

```bash
# Reproduce a specific commit's results
make reproduce COMMIT=a3b4c5d

# Generate audit trail
make audit-trail FROM=2026-01-01 TO=2026-08-05
```

---

## Understanding Output

### Score Files (`reports/scores_YYYY-MM-DD.csv`)

**Columns:**
- `ticker`: Stock symbol
- `company_name`: Full name
- `rank`: 1 = best, higher = worse
- `composite_score`: 0-100 (durability + valuation + momentum)
- `durability_score`: 0-50
- `valuation_score`: 0-35
- `momentum_score`: 0-15
- `is_excluded`: True/False (any red flags?)
- `exclusion_reason`: Why excluded (if applicable)
- `market_cap`: Current market capitalization
- `sector`: GICS sector
- `insider_score`: Bonus points from insider purchases
- `congress_score`: Bonus points from congressional trades
- `13f_score`: Bonus points from institutional conviction

**How to read it:**
- Top 60 ranks: Eligible for purchase
- Ranks 61-70: Buffer zone (hold but don't buy new)
- Ranks 71+: Not in portfolio

**What to look for:**
- Your current holdings' ranks (are they slipping?)
- New names in top 60 (potential buys)
- Exclusions in top 60 (things that would have scored well but were excluded)

### Proposal Files (`reports/proposal_YYYY-MM-DD.txt`)

**Example output:**
```
=== TRADE PROPOSAL 2026-08-05 ===

SUMMARY:
  Current positions: 22
  Target positions: 20
  Proposed buys: 3
  Proposed sells: 5
  Net change: -2 positions
  Turnover: 12% (annualized: 48%)

BUY ORDERS:
  AAPL: 100 shares @ limit $180.50 = $18,050
    Reason: New entry, rank 45 (entered top 60)
    Scores: D=42, V=28, M=12 → 82 composite
    Sector: Technology (current sector weight: 18% → 21%)
    Insider activity: 3 Form 4 purchases in last 90 days
    
  MSFT: 75 shares @ limit $420.00 = $31,500
    Reason: New entry, rank 38
    Scores: D=45, V=30, M=10 → 85 composite
    
SELL ORDERS:
  IBM: 150 shares @ limit $140.00 = $21,000
    Reason: Durability < 50 for 2 consecutive quarters (C1)
    Current rank: 145 (below hold threshold)
    Lots selected: [Lot #45: 100sh @ $150.00 (LT), Lot #52: 50sh @ $148.00 (LT)]
    Tax impact: Short-term loss: $0, Long-term loss: $1,300
    Tax savings: ~$195 (15% LT rate)
    Held since: 2023-04-12 (28 months)
    
HOLD (no action):
  [17 other positions - see detailed report]

TAX IMPACT SUMMARY:
  Total realized ST gains: $0
  Total realized LT gains: -$1,300
  Estimated tax due: $0 (loss carries forward)
  Tax alpha vs FIFO: $85

PORTFOLIO IMPACT:
  Total capital deployed: $49,550
  Total capital freed: $21,000
  Net cash required: $28,550
  Post-trade cash: $71,450
  Post-trade stock value: ~$800,000
  
WARNINGS:
  - Technology sector weight increasing 18% → 21%
  - Consider diversification
```

**How to review:**
1. Check each BUY's scores and reason
2. Verify each SELL's trigger (C1-C5)
3. Review tax impact (any large ST gains?)
4. Check sector concentrations
5. Verify you have cash for net capital required

### Backtest Reports

**Example output:**
```
=== BACKTEST RESULTS 2020-2024 ===

RETURNS:
  Strategy (pre-tax): 68.2%
  Strategy (after-tax): 62.5%
  S&P 500: 58.3%
  
  Annualized:
    Strategy: 11.4%
    S&P 500: 10.2%
  
RISK:
  Strategy volatility: 18.5%
  S&P 500 volatility: 16.2%
  Strategy max drawdown: -24.3% (Mar 2020)
  S&P 500 max drawdown: -33.9% (Mar 2020)
  
RISK-ADJUSTED:
  Sharpe ratio: 0.62
  Sortino ratio: 0.89
  Calmar ratio: 0.47
  
TAX:
  Tax alpha: 1.2% annualized
  Tax rate (effective): 9.1%
  FIFO counterfactual: 10.8% tax rate
  
TURNOVER:
  Average annual: 22%
  Transaction costs: -0.8% cumulative
  
PORTFOLIO:
  Avg positions held: 21.3
  Avg holding period: 26 months
  Longest holding: 48 months
  
FACTOR IC:
  Durability: 0.068 (t=3.2)
  Valuation: 0.041 (t=2.1)
  Momentum: 0.053 (t=2.8)
```

**How to interpret:**
- **Returns**: Did you beat the benchmark?
- **Risk**: Did you take more/less risk to get those returns?
- **Sharpe ratio**: Return per unit of risk (>0.5 is decent, >1.0 is excellent)
- **Max drawdown**: Worst peak-to-trough decline (can you stomach this?)
- **Tax alpha**: Value added by smart lot selection
- **Factor IC**: Are your signals actually predictive? (>0.05 is good)

---

## Troubleshooting

### Common Issues

#### "ImportError: No module named 'durable'"

**Cause:** Virtual environment not activated.

**Fix:**
```bash
source .venv/bin/activate
# Or just use: make test (it handles this automatically)
```

#### "API Error 401: Unauthorized"

**Cause:** Invalid or missing API key.

**Fix:**
1. Check `.env` file has correct keys
2. Verify keys are still valid (check broker website)
3. Ensure no extra spaces or quotes around keys

#### "Firewall assertion failed: future data detected"

**Cause:** You're trying to use data that wasn't available at the `as_of` date.

**Fix:**
- This is a FEATURE - it caught a potential look-ahead bug
- Check the error message for which rows are problematic
- Verify your data ingestion included proper `available_at` timestamps

#### "Reconciliation failed: position mismatch"

**Cause:** Internal ledger doesn't match broker.

**Fix:**
1. STOP trading immediately
2. Run `make reconcile` with verbose output
3. Compare `reports/ledger.csv` to broker statement
4. Manually correct the discrepancy
5. Only resume trading after reconciliation passes

#### Tests are failing after update

**Fix:**
```bash
# Re-run ingest in case data format changed
make ingest

# Clear cache
make clean

# Re-run tests
make test
```

If still failing, check Git log for breaking changes:
```bash
git log --oneline -10
```

#### "Out of memory" during backtest

**Cause:** Trying to backtest too long a period at once.

**Fix:**
```bash
# Break into smaller segments
make backtest SEGMENT=2020-2021
make backtest SEGMENT=2022-2023
make backtest SEGMENT=2024-2024
```

### Getting Help

1. **Check documentation first:**
   - `README_SIMPLE.md` for basics
   - `HOW_IT_WORKS.md` for technical details
   - This guide for workflows

2. **Search the codebase:**
   ```bash
   grep -r "error message text" src/
   ```

3. **Ask Claude Code:**
   ```bash
   claude
   # Then: "I'm getting error X, what does it mean?"
   ```

4. **Check test files:**
   Tests show working examples:
   ```bash
   grep -r "def test_" tests/ | grep durability
   ```

5. **Review recent changes:**
   ```bash
   git diff HEAD~5 HEAD
   ```

---

## Going Live (Real Money)

**⚠️ CRITICAL: Do not rush this. Stay in paper trading until you're 100% confident.**

### Prerequisites for Live Trading

Before even considering live trading:

- [ ] Ran in paper mode for at least 3-6 months
- [ ] Understand every command in this guide
- [ ] Have executed at least 3 full rebalancing cycles
- [ ] Reviewed and understood every proposed trade
- [ ] Your paper trading results match expectations
- [ ] Passed reconciliation checks every time
- [ ] Understand the tax implications
- [ ] Have reviewed all code (or trust it)
- [ ] Employer policies allow personal trading (if applicable)
- [ ] Consulted with a financial advisor (recommended)
- [ ] Consulted with a CPA about tax strategy

### Risks to Consider

**Financial Risks:**
- Strategy might underperform
- Transaction costs and taxes
- Market crashes (2008, 2020)
- Individual stock blowups
- Data errors leading to bad trades

**Operational Risks:**
- API key leaks
- Broker API downtime
- Bugs in code
- Incorrect tax reporting
- Wash sale mistakes

**Psychological Risks:**
- Panic selling in downturns
- Overtrading after good performance
- Confirmation bias
- Attribution errors (luck vs. skill)

### The Live Trading Checklist

When you're truly ready:

#### Step 1: Fund a Live Account

1. Open a live brokerage account (Alpaca or similar)
2. Fund with ONLY the capital you're comfortable risking
   - Recommended: Start with 25-50% of your target allocation
   - Example: If your target is $80,000 in Sleeve C, start with $20,000-$40,000
3. Get live API keys (different from paper keys!)

#### Step 2: Update Configuration

**Edit `.env`:**
```bash
# OLD (paper):
ALPACA_BASE_URL=https://paper-api.alpaca.markets

# NEW (live):
ALPACA_BASE_URL=https://api.alpaca.markets
ALPACA_API_KEY=<your_live_key>
ALPACA_SECRET_KEY=<your_live_secret>
```

**Edit `config/config.yaml`:**
```yaml
execution:
  live_trading_approved: false  # Keep FALSE for now
  max_order_value: 5000  # Lower limit for first live trades
```

#### Step 3: Test with ONE Small Trade

```bash
# Generate a proposal
make propose AS_OF=$(date +%Y-%m-%d)

# Manually edit to keep ONLY one small buy order
nano reports/proposal_YYYY-MM-DD.json

# Submit
make submit
```

**Verify:**
1. Order appeared in broker interface
2. Order filled as expected
3. Reconciliation passes
4. You're comfortable with the process

#### Step 4: Gradually Scale Up

- Week 1: 1-2 small positions
- Week 2-4: Add 3-5 more if all went well
- Month 2-3: Build to 50% target
- Month 4-6: Build to 100% target if confident

**Never rush this.**

#### Step 5: Set `live_trading_approved: true`

Only after you've successfully executed 5+ trades manually:

```bash
# Edit config manually (hooks prevent Claude from doing this)
nano config/config.yaml

# Change:
live_trading_approved: true
```

This removes some safety prompts, but execution still requires your approval.

### Live Trading Best Practices

**DO:**
- Start small and scale gradually
- Keep detailed records of every trade
- Reconcile after every trade
- Review proposals even more carefully
- Keep emergency cash reserves
- Have a "KILL file" procedure

**DON'T:**
- Trade with money you need in < 5 years
- Panic sell in downturns
- Overtrade after good performance
- Ignore sell rules because you "like" a stock
- Skip the reconciliation step
- Trade while emotional

### Emergency Stop

If anything goes wrong:

```bash
# Create a KILL file (blocks all execution)
touch KILL

# Or edit config:
nano config/config.yaml
# Set: live_trading_approved: false
```

The system checks for the KILL file before every trade submission.

---

## Maintenance & Updates

### Weekly Maintenance (5 minutes)

```bash
# Update data
make ingest

# Run tests
make test

# Check for any warnings
make lint
```

### Monthly Maintenance (15 minutes)

```bash
# Generate monthly report
make report TYPE=monthly

# Review calibration
make calibration

# Update decision journal
make journal

# Check for code updates
git fetch origin
git log HEAD..origin/main  # See what's new
```

### Quarterly Maintenance (1 hour)

- Full rebalancing (see [Quarterly Rebalancing](#quarterly-rebalancing))
- Review strategy performance
- Update `docs/` if you learned something
- Backup your database and reports
- Review and update config if needed

### Yearly Maintenance (2-3 hours)

```bash
# Generate annual report
make report TYPE=annual

# Export for taxes
make tax-export YEAR=2025

# Review all decisions from the year
make calibration YEAR=2025

# Update research export
make research-export
```

- Meet with CPA to review tax strategy
- Review employer policies (if applicable)
- Reassess risk tolerance
- Update preregistered hypotheses
- Write up lessons learned

### Backups

**What to backup:**
- `data/` directory (point-in-time database)
- `reports/` directory (all generated reports)
- `config/config.yaml` (your settings)
- `.env` file (but keep it secure!)
- `research/` directory (decision journal, claims)

**How to backup:**
```bash
# Create a timestamped backup
tar -czf backup_$(date +%Y%m%d).tar.gz data/ reports/ config/ research/

# Store securely (encrypted external drive, private cloud)
# DO NOT commit to public GitHub (contains your data)
```

### Updating the Code

When new features are released:

```bash
# Save your current state
git stash

# Pull updates
git pull origin main

# Restore your changes
git stash pop

# Reinstall dependencies (if needed)
uv sync

# Run tests to ensure compatibility
make test

# Review CHANGELOG.md for breaking changes
cat CHANGELOG.md
```

---

## Advanced Usage

### Custom Scoring Functions

If you want to experiment with different factor weights:

1. **Copy the default config:**
   ```bash
   cp config/config.yaml config/my_experiment.yaml
   ```

2. **Edit weights:**
   ```yaml
   scoring:
     weights:
       durability: 0.60  # Increased from 0.50
       valuation: 0.25   # Decreased from 0.35
       momentum: 0.15    # Same
   ```

3. **Run with custom config:**
   ```bash
   make score AS_OF=2026-08-05 CONFIG=config/my_experiment.yaml
   make backtest SEGMENT=2020-2024 CONFIG=config/my_experiment.yaml
   ```

4. **Log the experiment:**
   ```bash
   # Add to experiment log
   echo "2026-08-05,durability_60,Increased durability weight to 60%" >> reports/experiment_log.csv
   ```

**IMPORTANT:** Log every experiment so you can correct for multiple testing when evaluating results.

### Adding Custom Exclusions

Exclude specific stocks or sectors:

```yaml
# In config/config.yaml
exclusions:
  tickers:
    - "TSLA"  # Example: exclude Tesla
    - "GME"   # Example: exclude GameStop
  sectors:
    - "Tobacco"
    - "Weapons Manufacturing"
  reason: "Personal ethical preference"
```

### Integrating External Signals

Want to add your own signals? Here's how:

1. **Add signal data to database:**
   ```python
   # src/durable/signals/my_signal.py
   def compute_my_signal(ticker: str, as_of: date) -> float:
       """Your signal logic here."""
       return signal_value
   ```

2. **Add to overlays:**
   ```python
   # In src/durable/factors/overlays.py
   from durable.signals.my_signal import compute_my_signal
   
   def my_signal_overlay(df, as_of):
       df["my_signal"] = df["ticker"].apply(
           lambda t: compute_my_signal(t, as_of)
       )
       return df
   ```

3. **Log separately:**
   ```python
   # So you can test if it adds value
   df["my_signal_contribution"] = df["my_signal"] * 0.02  # Cap at 2 points
   ```

4. **Test in backtest:**
   ```bash
   make backtest SEGMENT=2020-2024
   # Check if IC improved
   make ic FACTOR=my_signal
   ```

### Running CPCV with Custom Parameters

```bash
# Default: 120 combinations
make cpcv

# Custom: more splits (slower but more robust)
make cpcv N_SPLITS=12  # Default is 10

# Custom: different test fraction
make cpcv TEST_FRACTION=0.25  # Default is 0.20
```

### Batch Backtesting Multiple Configurations

```bash
# Create a script
cat > run_experiments.sh <<'EOF'
#!/bin/bash
for weight in 0.4 0.5 0.6; do
  echo "Testing durability weight: $weight"
  make backtest SEGMENT=2020-2024 DURABILITY_WEIGHT=$weight
  make ic FACTOR=durability DURABILITY_WEIGHT=$weight
done
EOF

chmod +x run_experiments.sh
./run_experiments.sh
```

**Remember:** Log every experiment to avoid p-hacking.

### Automating Reports (Read-Only!)

You can automate reports (but NOT trading):

```bash
# Add to crontab
crontab -e

# Run monthly report on the 1st of each month
0 9 1 * * cd /path/to/durable-alpha && make report TYPE=monthly

# Run weekly portfolio review on Sundays
0 18 * * 0 cd /path/to/durable-alpha && make report TYPE=portfolio
```

**Never automate:**
- `make propose`
- `make submit`
- Anything that touches the broker API

### Jupyter Notebook Analysis

Want to explore data interactively?

```bash
# Install Jupyter (if not already)
uv pip install jupyter

# Start notebook server
jupyter notebook

# Create new notebook in notebooks/
```

Example notebook:
```python
import pandas as pd
from durable.data.store import as_of, connect

# Connect to database
conn = connect()

# Load scores
scores = pd.read_csv("reports/scores_2026-08-05.csv")

# Analyze
scores.groupby("sector")["composite_score"].mean().sort_values()
```

---

## Summary Cheat Sheet

### First Time
```bash
uv sync
cp .env.example .env
# Add API keys to .env
make test
make ingest
```

### Quarterly Rebalancing
```bash
make ingest
make score AS_OF=$(date +%Y-%m-%d)
make propose AS_OF=$(date +%Y-%m-%d)
# Review proposal carefully
make submit
make report TYPE=quarterly
make journal
```

### Common Commands
```bash
make test              # Run all tests
make ingest            # Update data
make score             # Score all stocks
make propose           # Generate trade proposal
make submit            # Execute trades
make reconcile         # Verify broker matches
make report TYPE=X     # Generate report
make backtest          # Test on history
make cpcv              # Validate robustness
make ic FACTOR=X       # Test factor quality
make tax-review        # Check tax opportunities
make dossier TICKER=X  # Research a stock
```

### Safety Checklist Before Any Trade
- [ ] Tests passing
- [ ] Data updated
- [ ] Proposal reviewed and understood
- [ ] Tax impact acceptable
- [ ] Reconciliation passed
- [ ] Not trading while emotional
- [ ] No employer blackout period
- [ ] Have time to monitor execution

---

## Conclusion

This system is a tool, not a guarantee. Use it thoughtfully:

1. **Start in paper trading** - no rush to risk real money
2. **Understand every trade** - if you don't know why you're buying something, don't buy it
3. **Follow the process** - the rules exist for good reasons
4. **Measure everything** - calibration matters more than returns
5. **Stay humble** - most active strategies fail; you might too
6. **Learn continuously** - that's the real value here

**The goal isn't to get rich - it's to build a disciplined, measurable, honest investment process that you can refine over decades.**

Good luck!

---

**Questions?** Check:
- `README_SIMPLE.md` for beginner concepts
- `HOW_IT_WORKS.md` for technical details
- `docs/` for specific subsystems
- Tests for working examples
- Ask Claude Code for clarification

**Updates to this guide:** This is a living document. As you learn things that should be here, add them:
```bash
nano USER_GUIDE.md
git add USER_GUIDE.md
git commit -m "Update user guide with X"
```

---

*Not financial advice. For educational purposes. Past performance doesn't guarantee future results. Consult professionals for tax and financial advice. Start with paper trading. Understand the risks.*
