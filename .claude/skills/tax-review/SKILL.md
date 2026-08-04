---
name: tax-review
description: Review tax lots, identify loss-harvesting candidates, run wash-sale checks, and estimate tax alpha.
---

# Tax review

Read `docs/11_TAX_ENGINE.md` and `.claude/rules/tax-correctness.md`.

1. Load all lots across ALL accounts (taxable, Roth, traditional IRA).
2. Classify: unrealized gain/loss, holding period, days until long-term.
3. **Harvest candidates**: loss >= 8% AND >= $150, TAXABLE ONLY.
4. **Wash-sale check**: 61-day window, scanning EVERY account, DRIP counted as a purchase.
5. **Lot selection**: HIFO or long-term-first, whichever yields higher after-tax proceeds.
6. **Long-term watch**: positions within 60 days of 12 months → "wait N days" list.
7. **Tax alpha**: after-tax return vs a naive-FIFO no-harvesting counterfactual.

## Always say
Tax alpha **decays** as basis falls — early-year numbers do not extrapolate · for a low-income
student the $3,000 offset is worth less now than carrying forward to higher-earning years, model
both · never harvest a name the screen wants to buy this quarter · recommend CPA confirmation.
