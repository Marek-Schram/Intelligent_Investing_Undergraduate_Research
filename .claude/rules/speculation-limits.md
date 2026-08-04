---
description: Hard constraints for the Sleeve E discovery module.
paths: ["src/durable/discovery/**", "docs/08_DISCOVERY_ENGINE.md"]
---

# Rule: Speculation limits (Sleeve E)

Also enforced by `.claude/hooks/guard_write.sh`.

## Universe — never relax
1. **Exchange-listed only.** NYSE/NASDAQ/AMEX. Hard-exclude OTC/OTCBB/Pink/Expert, now or
   within 24 months. No exceptions, no config override.
2. **Price >= $5.00.** 3. **Cap $300M–$3.0B.** 4. **Float >= $150M and >= 8M shares.**
5. **ADV >= $1.5M.** If you cannot exit, you do not own it — you are trapped in it.
6. **Profitable in >= 3 of last 4 years.** The size premium survives only with a quality filter.
7. **>= 12 quarters filed, >= 36 months since IPO.**
8. **Short interest > 10% of float => exclusion.** 9. **Distance-to-default < 1.5 => exclusion.**

## Automatic permanent exclusions
Reverse split within 24m · >1 name/ticker change in 5y · reverse-merger within 5y · SEC trading
suspension ever · repeated late filings · auditor resignation or restatement within 24m · share
count +25% in one year · any detected paid promotion.

## Sizing — never raise
10. Sleeve E <= **2% of total portfolio**, carved OUT of Sleeve C.
11. Max **8 positions**, each <= **0.25% of total**. 12. Position <= 1% of 60-day median ADV.
13. **Never increase the cap because performance was good.**

## Entry
14. Staged tranches 40/30/30, min 90 days apart.
15. Tranches gate on **business confirmation**, never price decline. Never write code that adds
    to a position because it fell.
16. Score >= 75 to open, >= 65 to watchlist. Below 60 cancels remaining tranches.

## Sourcing
17. **A candidate learned from any unsolicited source is permanently excluded** — social media,
    DMs, forums, videos, group chats, newsletters. Only the systematic screens qualify.

## Behavior
18. Never "the next [company]", "multi-bagger", or "moonshot".
19. Never suppress a manipulation flag because fundamentals look good. The flags win.
20. Every Sleeve E buy requires a written bear case (`adversarial-review` skill).
