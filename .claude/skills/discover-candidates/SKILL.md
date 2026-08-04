---
name: discover-candidates
description: Run the Sleeve E discovery workflow to find under-followed high-quality small caps, screen for manipulation, and produce a Discovery Dossier.
---

# Discovery workflow (Sleeve E)

Read `docs/08_DISCOVERY_ENGINE.md` and `.claude/rules/speculation-limits.md`. Highest-risk module.

1. **Universe** — every filter in §3. Log a `reason` for every exclusion. **Missing data =>
   excluded**, never imputed.
2. **Seven screens** — coverage-gap · boring-industry · insider-cluster · spin-off ·
   filing-language · quiet-compounder · institutional-conviction. Union, de-duplicate.
   EDGAR: User-Agent with name+email, <=10 req/sec, CIKs zero-padded to 10 digits.
3. **Manipulation screen FIRST, scoring second.** Every check in §5 plus distance-to-default
   and short interest. A single hit is permanent exclusion. Never let fundamentals override.
4. **Score** — durability gate (>=30/50) → neglect → valuation vs small-cap peers → quality
   evidence → overlays. Watchlist >= 65, position-eligible >= 75.
5. **Adversarial review — required.** Invoke `adversarial-review`; the bear case goes in the dossier.
6. **Dossier** per §9, including every manipulation check with its result (including the ones
   that passed), the three biggest ways this could be wrong, and the blank "mistake" line.
7. **Tranche** — T1 only for new names (40%, max 0.25% of total portfolio).

## Hard stops
Never above 0.25% of total · never more than 8 positions · never OTC, sub-$5, or unprofitable ·
never a name from an unsolicited source (say so plainly) · no promotional language · ends at a
dossier and proposal, never an order · always state the §10 caveat that the neglect premium is
contested and 8 positions will never be a meaningful sample.
