---
description: Correctness constraints for tax lot accounting and harvesting.
paths: ["src/durable/tax/**", "src/durable/execution/**"]
---

# Rule: Tax correctness

Tax bugs are silent. They surface a year later, in a letter, with interest.

1. **Every sale specifies lots explicitly.** Never let the broker default to FIFO.
2. **Wash-sale checks span ALL accounts** — taxable, Roth, traditional IRA, spouse. A
   cross-account wash sale permanently destroys the deduction rather than deferring it.
3. **61-day window**: 30 days before AND after, plus the sale date.
4. **Disallowed losses are ADDED to the replacement lot's basis**, holding period inherited.
5. **Dividend reinvestment counts as a purchase.** Model DRIP.
6. **Never harvest in a Roth or traditional IRA.**
7. `Decimal`, never `float`, for basis, proceeds, or gain. Fractional shares to 6 decimals.
8. Optimize **after-tax proceeds**, not minimum realized gain.
9. Every lot selection logs its reason. A CPA must be able to reconstruct it.
10. Backtests MUST report after-tax alongside pre-tax.
11. Never state tax conclusions as advice. Encode mechanics; recommend CPA confirmation.
