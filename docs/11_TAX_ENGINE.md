# 11 — Tax Engine

The highest-certainty return improvement available in a taxable account. Not a prediction —
arithmetic.

## 0. Plain-English
When you sell shares bought at different times, you choose *which* ones. Sell the expensive ones
and you owe less tax. Most people never choose, so the broker picks — usually the worst option.
Separately: even in a great year plenty of stocks fall. Sell a loser, use the loss to cancel tax
on winners, buy something similar to stay invested, wait 31 days. That's the tax code working as
designed — and unlike everything else here, it doesn't depend on being right about anything.

## 1. Why this earns a module
Direct-indexing research puts tax alpha at **0.5%-1.5%/yr** in early years, decaying as basis
falls. Next to this project's honest expectation for stock selection — where the base rate of
beating an index is low and a good outcome is *matching* it — **a reliable 50-150bps of
after-tax improvement may be larger and far more certain than any selection alpha.**

Available every year regardless of direction: the S&P 500 returned +26% in 2023 while **143 of
500 components declined**; +25% in 2024 with ~160 falling. The Schwab 1000 returned nearly 25% in
2024 while **433 constituents lost value**.

You hold ~20-28 positions, small next to a 500-stock direct-index account — so the dollar benefit
is modest, but the logic is identical, it's free, and it teaches mechanics that matter for your
whole career.

## 2. Lot-level accounting
Every purchase creates a tax lot: `lot_id, ticker, sleeve, account, acquired_at, shares,
cost_basis_per_share, adjusted_basis, wash_sale_deferred, holding_start, closed_at, proceeds,
realized_gain, term`. Fractional shares to 6 decimals. Broker lots reconciled nightly; a mismatch
blocks trading. **Every sale specifies lots explicitly — never let the broker default to FIFO.**

## 3. Lot selection
**HIFO** (default) · **long-term-first** (often beats raw HIFO when short-term gains would be
taxed at your marginal rate) · **loss-first** (when harvesting) · **FIFO never chosen by us**.

**The optimizer maximizes after-tax proceeds, not minimum realized gain.** Those differ: a
short-term lot with a small gain can cost more than a long-term lot with a larger one. Selection
logs its reason so a CPA can reconstruct it.

## 4. Harvesting
Sell below basis, immediately buy a **correlated but not substantially identical** replacement,
optionally swap back after the window. Losses offset gains dollar-for-dollar, then up to
**$3,000** of ordinary income (IRC §1211), remainder carrying forward indefinitely.

**Our rules:** trigger at loss >= 8% **and** >= $150 · monitored monthly, executed at quarterly
rebalance unless loss > 20% · replacement is a **sector ETF proxy, never another screened single
stock** · original repurchasable after **31 days** if still top-60 · **taxable accounts only** ·
**never harvest a name we'd otherwise buy this quarter.**

**Honest limits.** Tax alpha **decays** as basis falls. The benefit assumes you have a use for
the losses. **As a 19-year-old with modest income, your $3,000 offset is worth less than it will
be later — carrying losses forward to higher-income years is often the better plan.** Model both.

## 5. Wash-sale engine
Disallowed if you acquire a substantially identical security within **30 days before or after** —
a 61-day window — and the disallowed loss is **added to the replacement's basis** rather than lost.

**Three traps:**
1. The rule reaches **across accounts**, including IRAs and a spouse's. Taxable harvest + Roth
   purchase = **permanently lost** deduction, not deferred.
2. **Automatic dividend reinvestment counts as a purchase.** Turn DRIP off on anything you might
   harvest, or model it.
3. The replacement's **holding period inherits** from the original lot.

`execution/propose.py` refuses any buy that would trigger a wash sale, naming the conflicting lot.

## 6. Account location
**Sleeve E → Roth IRA** (highest variance and turnover risk; wins tax-free, no wash-sale
bookkeeping) · **Sleeve C → taxable** (long holds get long-term rates and provide harvestable
lots) · bonds → traditional IRA if available · index/factor ETFs → either.

**Caution:** Sleeve E in the Roth plus a correlated name in taxable can create a cross-account
wash sale. The engine checks both.

## 7. Reporting
Realized ST vs LT YTD · harvested losses and carryforward · **tax alpha vs a naive-FIFO
no-harvesting counterfactual** — the honest measure · wash-sale disallowances with triggering
trades named · positions approaching 12 months ("wait N days") · estimated annual tax drag.

The backtest reports after-tax alongside pre-tax. **A strategy that wins pre-tax and loses
after-tax is a losing strategy**, and this module is what reveals it.

*Not tax advice. Encode mechanics; confirm with a CPA. Re-verify rules annually.*
