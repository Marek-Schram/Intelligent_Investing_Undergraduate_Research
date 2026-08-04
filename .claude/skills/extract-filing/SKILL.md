---
name: extract-filing
description: Run structured LLM extraction over an SEC filing to pull risk-factor deltas, red-flag language, revenue durability markers, and concentration data with citations.
---

# Filing extraction

Read `docs/10 §1` and `.claude/rules/llm-extraction.md`.

**The rule that matters most: every extracted claim carries an accession number and a section
citation. No citation, no score contribution.** That is what keeps hallucination out of the
portfolio.

## Steps
1. Check the cache: (accession, prompt_version, model_version). Hit => return it. Never
   re-extract silently; that breaks reproducibility.
2. Fetch via edgartools. Record the acceptance timestamp — that becomes `available_at`, NOT
   the time you ran the extraction.
3. Extract into the fixed JSON schema: risk_factor_delta · red_flags · revenue_durability ·
   concentration · segments · capital_allocation · language_shift · toxic_financing. Each field
   carries `value`, `citation`, `confidence`.
4. Temperature 0. Log the model version.
5. Low confidence or missing section => **null**. Never guess.

## Never
- Ask for a price, return, rating, or recommendation. **Extraction, not prediction.** The
  evidence in `docs/13 §1` is that LLM predictions on pre-cutoff periods measure memory.
- Parse a number out of free-form prose.
- Use an extraction in a window predating the training cutoff without marking it CONTAMINATED.

## Quarterly obligation
Spot-check 10% against actual filing text; log the error rate to reports/extraction_audit.csv.
An unaudited extraction pipeline is a liability, not an asset.
