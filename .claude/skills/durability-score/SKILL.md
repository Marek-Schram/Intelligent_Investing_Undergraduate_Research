---
name: durability-score
description: Compute and sanity-check the durability score (SPEC section 2) for tickers as of a date. Use when the user asks how durable, high-quality, or financially strong a company is.
---

# Durability score

1. Load facts via `store.as_of(date)` — never raw tables. Confirm the firewall passed.
2. Require >= 8 quarters filed. Financial (SIC 60xx-64xx)? Use the §2.6 variant and say so.
3. Order: F-Score → ROIC → cash/balance sheet → growth durability → distance-to-default → red flags.
4. Red-flag penalties last. Three triggers => excluded regardless of score.

**Output:** a table with sub-score, points earned, points possible, and the RAW INPUTS that
produced each. A score with no visible inputs is not reviewable. Then one sentence each: the
strongest thing about this business; the weakest; what would have to change for the score to
fall 10 points.

**Sanity checks:** ROIC > 100% => check for negative/near-zero invested capital, report the
caveat not the number · F-Score 9 with declining revenue => verify YoY used fiscal not calendar
periods · any `fillna` => flag it, missing is not zero · DD < 2.0 red flag, < 1.0 exclusion ·
cross-check one ratio externally, but note published ratios differ by methodology.
