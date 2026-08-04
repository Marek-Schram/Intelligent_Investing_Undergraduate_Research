# 12 — Research Workflow

Infrastructure for the *research project* half: literature management, a decision journal with
calibration scoring, and reproducibility. This turns "I built a trading bot" into "I ran a study."

## 0. Plain-English
Three things researchers do that traders usually don't:
1. **Track what you read**, so every claim points to a real source.
2. **Write predictions down before you find out** — with how confident you were — then score
   yourself. Most people are badly overconfident and never discover it, because they never wrote
   anything down.
3. **Make everything reproducible**, so anyone can regenerate every number from committed files.

The second is the interesting one. **Your returns won't be statistically meaningful for a decade.
Your calibration will be measurable in about a year** — and it's publishable either way.

## 1. Literature
```
research/
  literature/  library.bib · notes/<citekey>.md · claims.csv · reading_log.csv
  protocol/    preregistration.md · amendments.md
  journal/     decisions.csv · calibration.md
```

**The claims ledger** is the important part. Every empirical claim in the repo gets a row:
`claim_id · claim · citekey · page_or_section · effect_size · sample_period · **contradicted_by**
· used_in · confidence`.

**Why `contradicted_by` matters more than it looks:** the neglect premium, the small-cap premium,
and 13F cloning all have contradicting literature. That column forces you to record the
disagreement rather than cite only the study you liked. It is the difference between a research
project and a rationalization.

**Tooling:** Zotero + `pyzotero` + Better BibTeX for stable citekeys; a Zotero MCP server lets
Claude Code search your library in-session.

**Preregistration:** before testing any new signal, write the hypothesis, prediction, test, and
threshold into `protocol/preregistration.md` and **commit it**. A committed timestamp is proof
you didn't decide what you were looking for after seeing the answer, and it feeds the Deflated
Sharpe trial count.

## 2. Decision journal and calibration
**Schema:** `decision_id · date · type · ticker · sleeve · prediction (falsifiable, with a
horizon) · confidence (50-99, stated BEFORE the outcome) · reasoning · key_assumption ·
**disconfirming_evidence (may not be empty)** · emotional_state · system_score · overrode_system
· resolution_date · outcome · resolved_correct`.

If you struggle to fill `disconfirming_evidence`, run the **`adversarial-review` skill** — the
`bear-analyst` subagent generates a real counter-case in its own context, which is far stronger
than the one you'd write unaided.

**Scoring.** Brier score $BS = \\frac{1}{N}\\sum(f_i - o_i)^2$ (0.25 = always saying 50%) ·
**calibration curve** with bin counts, sparse bins flagged not smoothed · **overconfidence ratio**
(mean confidence / hit rate; above 1.0 is the overwhelmingly common result) · **discrimination**
(a well-calibrated person who can't discriminate is just accurately uncertain) · **calibration by
emotional state** — the finding that actually changes behavior · **override performance**
cross-referenced with `reports/overrides.md`.

**Honest note.** ~20 decisions a year means ~3 years for confident conclusions. Say so. But the
*process* of writing a falsifiable prediction with a confidence number before acting is itself
the intervention — it improves decisions immediately, whether or not enough get scored.

## 3. Reproducibility contract
`methodology.md` pins: git commit · snapshot IDs · config hash · `uv.lock` versions · **seeds for
every stochastic process** (bootstrap, CPCV path ordering, placebo shuffles) · LLM model and
prompt version hashes · contamination verdict · trial count.

**`make reproduce COMMIT=<hash>` must regenerate a prior report byte-identically.** If it can't,
the result is not a research finding — it's an anecdote with a chart.

`reports/experiment_log.csv` columns: `run_id · date · hypothesis_id · preregistered ·
segment_used · params_changed · seed · llm_model_version · prompt_version · cagr · sharpe ·
max_dd · pbo · mean_ic · notes`. **Every run, including the ones you don't like.**

## 4. Paper scaffold
Abstract · Introduction (framed as a question) · Literature review (generated from claims.csv,
**including contradicting evidence**) · Data (sources, PIT construction, survivorship, exclusions)
· Methodology (score, protocol, CPCV, IC, costs, tax) · Results (walk-forward, CPCV distribution,
PBO, ablations, factor attribution, IC, after-tax, calibration) · Discussion · **Limitations** ·
Conclusion.

**Write limitations before results exist.** It may grow, never shrink. Draft now: single realized
path · small live sample · LLM contamination for pre-cutoff windows · neglect premium contested ·
small-cap premium quality-dependent · 13F long-only with 45-day lag · author is one
non-professional investor with a small account and modeled rather than observed costs.

## 5. What a good outcome looks like
> The most likely honest finding is that a quality-value screen produces returns explainable by
> known factor exposures, and that the marginal signals — political disclosures, institutional
> conviction, neglect — add little after costs. **That is a real result.** A carefully executed
> study that fails to reject the null, with preregistered hypotheses, proper purged
> cross-validation, and honest uncertainty quantification, is better research than a study that
> finds spectacular alpha through undisclosed data mining.

The calibration analysis may end up the most interesting chapter — and it's the one nobody else
writes. So might the open-source audit in docs/13: **sorting that survey by popularity gives
almost exactly the inverse of sorting it by evidentiary standards**, and that is a finding.
