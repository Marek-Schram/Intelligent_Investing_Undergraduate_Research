---
description: Rules for any LLM-derived feature that feeds a score or decision.
paths: ["src/durable/signals/**", "docs/10_SIGNAL_EXTENSIONS.md"]
---

# Rule: LLM extraction discipline

Grounded in docs/13 §1: LLM trading agents cannot be honestly backtested before their training
cutoff, because they memorize outcomes rather than learn predictive relationships.

1. **Citation or nothing.** Every claim carries an accession number and section. No citation
   => scores ZERO.
2. **Structured output only.** Fixed JSON schema, enum-constrained fields. Never parse a number
   out of free-form prose.
3. **Extraction, not prediction.** Facts and changes a human analyst would extract. NEVER ask
   an LLM to forecast a price, return, or rating.
4. **Cache and version** by (accession, prompt_version, model_version). A prompt edit
   invalidates the cache and requires a backtest re-run.
5. **Point-in-time from the filing**, never from when the extraction ran.
6. **Temperature 0.** Log the model version to experiment_log.csv.
7. **Contamination guard.** Using an extraction in a backtest window before the model's
   training cutoff RAISES unless explicitly allowed, and then tags results CONTAMINATED and
   reports them separately. Never fold silently into headline results.
8. **Alpha-decay test required** (TICKET-045). Measure performance on both sides of the
   training cutoff. A sharp drop after the cutoff is measured contamination, and it must be
   reported rather than explained away.
9. **Audit 10% quarterly** against actual filings; log the error rate.
10. Low confidence or missing section => return null. Never guess.
