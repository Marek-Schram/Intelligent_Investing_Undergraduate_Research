---
name: adversarial-review
description: Run a structured bull-versus-bear review of a position before buying or at quarterly review, producing the disconfirming evidence the decision journal requires. Use before any buy, or when the user asks what could go wrong with a holding.
---

# Adversarial review

Adapted from the one genuinely transferable idea in multi-agent trading frameworks: a
**structured dialectic** where bull and bear cases are argued separately before a decision.
We take the structure and discard the autonomy — no agent trades here.

Read `docs/13 §2.5`. This exists because `disconfirming_evidence` in the decision journal may
not be empty, and unaided people generate weak counter-arguments they can easily dismiss.

## Procedure
1. **Bull case** (you, from the score): why the durability and valuation scores support this.
   State the sub-scores with raw inputs. 4-6 sentences.
2. **Bear case** — invoke the `bear-analyst` subagent in its own context. Give it the ticker,
   the filings, and the scores. Ask it to win, not to be balanced.
3. **Cross-examination**: for each bear point, state whether the bull case survives it, and how.
   Do not paper over a point you cannot answer — mark it OPEN.
4. **Falsifiers**: the three specific observables that would prove the bear right. These become
   the sell-rule triggers to watch and go into the memo verbatim.
5. **Verdict**: proceed / proceed smaller / decline / revisit next quarter. If any OPEN point is
   material, the default is decline.

## Rules
- The bear case must cite filings. Vibes do not count as disconfirming evidence.
- If the bear-analyst cannot build a case, that is a finding worth recording — but check that
  it was given the filings, the short interest, and the credit data before accepting it.
- Never resolve the debate by weighing "overall feel." Name which specific evidence settled it.
- The output feeds `research/journal/decisions.csv` `disconfirming_evidence` verbatim.
- **Required for every Sleeve E buy** (`.claude/rules/speculation-limits.md` rule 20) and
  recommended for every Sleeve C buy.
