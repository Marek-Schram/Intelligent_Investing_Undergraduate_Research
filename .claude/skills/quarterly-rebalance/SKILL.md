---
name: quarterly-rebalance
description: Run the live quarterly rebalance - score, construct, diff, tax-optimize, adversarial review, and generate an order proposal plus memo.
---

# Quarterly rebalance

3rd Friday of Feb / May / Aug / Nov.

1. Refresh ingestion; data-quality checks; **firewall audit**. Abort on failure.
2. Build the universe as of today.
3. Score: durability + valuation + momentum, then overlays (gated to top 40).
4. Construct: buffer-zone selection (top 60), equal weight, 6% position cap, 25% sector cap,
   15-25 positions.
5. Diff against holdings. **Every sell cites a rule S1-S5.** Unattributed sell = bug, stop.
6. **Adversarial review on every new buy** — invoke the `adversarial-review` skill. The bear
   case goes into the memo and the journal verbatim.
7. **Tax pass**: select lots (after-tax optimal), 61-day wash-sale check ACROSS ALL ACCOUNTS,
   flag short-term sales not driven by S2/S5, list harvest candidates.
8. Write `proposals/YYYY-MM-DD.json` and `reports/memo_YYYY-MM-DD.md`.
9. Generate the quarterly performance report.
10. Create decision-journal entries for every buy and sell, confidence stated BEFORE outcome.

## The memo, per buy
All sub-scores with raw inputs · reverse-DCF implied growth vs trailing FCF CAGR · red flags
checked including DD and short interest · **the bear case and its three falsifiers** · lots
being sold and the tax consequence · a blank line "What would have to be true for this to be a
mistake:" — **leave it blank for the human.**

## Hard stops
NEVER submit orders — ends at the proposal file. Enforce the 48-hour rule and state the
earliest permitted submission time. Lead with Sleeve C+E vs VTI since inception, first line.
