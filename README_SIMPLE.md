# Durable Alpha: Smart Investing Made Simple

## What Is This?

This is a computer program that helps you invest in the stock market intelligently. Think of it as a very careful, very patient investment assistant that follows strict rules.

**The Big Idea:** Buy about 20 really good companies at fair prices, and hold them for years. Don't panic when prices go down. Don't get greedy when prices go up. Just stick to the plan.

> **Don't want to type commands?** After the install steps below, run `make gui` to open a
> point-and-click browser version of this whole program, with numbered steps walking you
> through the order to do things in. See [GUI_GUIDE.md](GUI_GUIDE.md). Everything below still
> works exactly the same either way — the GUI just runs the same commands for you.

---

## How It Works (In Plain English)

### Step 1: Find Good Companies

The program looks for companies that have:
- **Strong businesses** - They make money consistently, don't waste cash, and aren't playing accounting tricks
- **Fair prices** - The stock price makes sense compared to how much money the company actually makes
- **Positive momentum** - The stock has been going up over the past year (the market is starting to agree it's good)

### Step 2: Check for Red Flags

Before buying anything, the program checks for problems:
- Is the company about to go bankrupt?
- Are insiders selling all their shares?
- Is the accounting suspicious?
- Are too many people shorting the stock (betting it will fail)?

If any serious red flags appear, **the company is skipped** - no matter how good it looks otherwise.

### Step 3: Buy and Hold

Once the program finds 15-25 good companies:
- It suggests buying them
- **A human (you) must approve every trade** - the computer never trades automatically
- You hold each stock for at least 12 months (usually longer)
- You only sell if one of five specific rules fires (like the company's business quality drops)

### Step 4: Save on Taxes

The program is smart about taxes:
- It tracks every share you buy separately
- When selling, it picks the shares that will cost you the least in taxes
- It "harvests" losses to offset gains
- It watches out for "wash sale" rules that could hurt you

### Step 5: Measure Everything

The program keeps detailed records:
- How much money did you make?
- How much risk did you take?
- Did the strategy actually beat the simple approach of just buying an index fund?
- What parts worked? What didn't?

---

## What Makes This Different?

### 1. **You Stay in Control**
- The program suggests trades
- **You** approve every single one
- No automatic trading, no surprises

### 2. **It's Honest About Uncertainty**
- Most investing systems claim they'll make you rich
- This one admits: **beating the market is really hard**
- Even if it just matches an index fund, you'll learn a ton and probably save money on taxes

### 3. **It Never Cheats**
- Many backtests (testing on past data) accidentally "peek at the future"
- This system has multiple safeguards to prevent that
- It only uses information that was actually available at the time

### 4. **It's Built for Learning**
- Every decision is logged
- You can see exactly why the computer recommended each trade
- Over time, you'll learn what works and what doesn't

### 5. **Small Scale = Smart Risk**
- Only **8% of your money** goes into this main strategy
- Only **2% more** goes into experimental small companies
- The other 90% stays in boring, safe index funds and bonds
- **If this entire system fails, you lose less than one year's tuition**

---

## The Five Parts of Your Portfolio

| Part | Percentage | What It Does |
|------|-----------|--------------|
| **Index Funds** | 70% | Boring global stocks - your safety net |
| **Factor ETFs** | 15% | Funds that tilt toward value, quality, momentum |
| **Durable Strategy** | 8% | The 15-25 companies this program picks |
| **Discovery Sleeve** | 2% | Small, under-followed companies (high risk) |
| **Bonds/T-Bills** | 5% | Ultra-safe cash-like investments |

**Why split it this way?** Even if the computer-picked stocks perform badly, you'll still do fine because 90% of your money is in proven, diversified investments.

---

## What You Need to Get Started

### Required
1. **API Keys** (free accounts):
   - SEC EDGAR (to download company financial reports)
   - FRED (for economic data like interest rates)
   - Alpaca (paper trading account - fake money for testing)

2. **Python 3.12** installed on your computer

3. **Basic comfort with a command line** (not coding knowledge - just typing commands)

### Installation

```bash
# 1. Navigate to this folder
cd "Investing with Claude/durable-alpha"

# 2. Install dependencies
uv sync

# 3. Copy the example files
cp .env.example .env
cp config/config.example.yaml config/config.yaml

# 4. Edit .env and add your API keys
# (Use any text editor)

# 5. Run the tests to make sure everything works
make test
```

---

## How to Use It

**Prefer a GUI?** Skip straight to `make gui` and follow the numbered steps in the sidebar —
it walks you through everything below in order. What follows is the command-line version of
the same steps, for reference.

### Check Stock Scores
```bash
make score AS_OF=2026-08-01
```
This shows you the top companies on a given date, with scores from 0-100.

### See What to Buy/Sell
```bash
make propose AS_OF=2026-08-01
```
This creates a list of suggested trades (but doesn't execute them).

### Run a Backtest (Test on Old Data)
```bash
make backtest SEGMENT=2020-2024
```
This shows how the strategy would have performed in the past.

### Generate a Report
```bash
make report TYPE=monthly
```
This creates a performance report showing returns, risk, and comparisons to benchmarks.

### Actually Trade (Paper Money Only at First)
```bash
make submit
```
This executes the proposed trades - but **only after you've reviewed and approved them**.

---

## Key Safety Features

### 1. **Paper Trading First**
The system starts in "paper trading" mode - it uses fake money so you can test everything without risk.

### 2. **Multiple Firewalls**
- A hook blocks the computer from turning on real trading by itself
- A hook blocks editing your API keys
- A hook prevents weakening safety limits
- Every trade requires human approval

### 3. **Look-Ahead Prevention**
The system has two independent checks to make sure it never uses information from the future when testing on past data.

### 4. **Dead Company Problem Solved**
When testing on data from 2008, the system includes Lehman Brothers, Bear Stearns, and Washington Mutual - companies that failed. Most systems quietly exclude them, which makes the backtest look better than it should.

### 5. **Clear Exit Rules**
You sell a stock **only if**:
1. Its durability score drops below 50 twice in a row
2. Its valuation becomes extremely expensive
3. A manipulation red flag fires (like sudden insider selling)
4. Liquidity dries up (can't sell easily)
5. A fundamental metric breaks (like debt exploding)

Price going down **is not a reason to sell**.

---

## What Success Looks Like

### Best Case
- You beat the S&P 500 by 1-3% per year after taxes
- You deeply understand every company you own
- You learn quantitative investing skills
- You save 0.5-1.5% per year just from smart tax management

### Realistic Case
- You roughly match the S&P 500's return
- You save meaningful money on taxes
- You build a reusable research system
- You gain confidence in your decision-making

### Worst Case (But Still Valuable)
- The stock-picking doesn't beat the index
- But you still make good returns (because 90% is in index funds)
- You learn what doesn't work
- You have data to improve the system

**Remember:** Your ability to make good predictions will be measurable in about a year. Whether the returns are truly good won't be clear for a decade.

---

## Important Warnings

### This Is Not
- Financial advice (I'm not a financial advisor)
- A get-rich-quick scheme
- Suitable for everyone
- Tested or verified by any regulatory body

### You Should
- Start with paper trading
- Understand that past performance doesn't predict future results
- Consult a tax professional for your specific situation
- Check any employer rules about personal trading
- Never invest money you can't afford to lose

### The Hard Truth
- Most people who try to beat the market fail
- This system might fail too
- The tax benefits might be the only real advantage
- **That's okay** - learning the process is valuable even if the returns are mediocre

---

## Questions You Might Have

### Q: Will this make me rich?
**A:** Probably not. It might beat the market slightly, or it might not. The goal is to match or slightly beat index funds while learning a lot.

### Q: How much time does this take?
**A:** 
- Initial setup: 2-3 hours
- Quarterly rebalancing: 1-2 hours
- Monitoring: 15 minutes per month

### Q: Do I need to know how to code?
**A:** No, but basic command-line comfort helps. The system gives you commands to copy-paste.

### Q: What if a stock crashes?
**A:** The system holds 15-25 stocks, so one bad stock only hurts a little. Also, it checks for bankruptcy risk before buying.

### Q: Can I customize the strategy?
**A:** Yes, but be careful. The system is designed with specific rules for good reasons. Changing them might break things.

### Q: How do I know it's not cheating on the backtest?
**A:** The code has a "firewall" module that throws errors if you accidentally use future information. Tests verify this works.

### Q: What about crypto, options, or day trading?
**A:** This system doesn't do any of that. It's boring on purpose.

---

## File Structure (Where Everything Lives)

```
durable-alpha/
├── src/durable/          ← The actual program code
│   ├── data/             ← Download and store financial data
│   ├── factors/          ← Calculate company quality scores
│   ├── portfolio/        ← Decide what to buy/sell
│   ├── backtest/         ← Test on historical data
│   ├── execution/        ← Actually place trades (with approval)
│   ├── reporting/        ← Generate performance reports
│   ├── tax/              ← Tax optimization logic
│   └── research/         ← Track decisions and measure calibration
├── tests/                ← 787 automated tests to verify everything works
├── docs/                 ← Detailed technical documentation
├── config/               ← Your settings and preferences
├── reports/              ← Generated performance reports
└── .env                  ← Your API keys (never share this file!)
```

---

## Next Steps

1. **Read `CLAUDE.md`** - This is the instruction manual for Claude Code (the AI assistant)
2. **Run `make test`** - Verify all 787 tests pass
3. **Run `make backtest`** - See how it would have done historically
4. **Run `make propose`** - Generate your first set of suggested trades (paper money)
5. **Review the proposals carefully** - Understand why each stock was chosen
6. **Learn as you go** - The system logs everything, so you can always look back

Or skip the typing entirely: run `make gui` and do all six of the above by clicking through the
numbered steps in the sidebar. See [GUI_GUIDE.md](GUI_GUIDE.md).

---

## Getting Help

- **Documentation:** Check the `docs/` folder for detailed explanations
- **Code comments:** Every function explains what it does and why
- **Test files:** The `tests/` folder shows examples of how everything works
- **CLAUDE.md:** Instructions for working with the AI assistant

---

## Final Thoughts

Investing is hard. Beating the market is even harder. This system tries to do it carefully, honestly, and transparently.

Even if it only matches index fund returns, you'll gain:
- Deep understanding of business quality
- Quantitative research skills
- Tax optimization knowledge  
- Decision-making discipline
- A reusable framework

And you'll lose at most 10% of your portfolio if it fails completely.

That's a good trade.

**Good luck!**

---

*This project is for educational and personal research. Not investment advice. Start with paper trading. Verify everything. Past performance doesn't guarantee future results. Consult professionals for tax and legal advice.*
