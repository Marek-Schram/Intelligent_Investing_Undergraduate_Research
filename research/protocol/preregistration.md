# Preregistration

**Commit BEFORE running any test.** A hypothesis written after seeing results is a description,
not a prediction. `research/preregister.py` compares git timestamps and raises on HARKing.

## H1 — Durability + valuation produces alpha after factor adjustment
Prediction: FF5+MOM alpha > 0 with |t| > 2 over validation (2011-2018).
Threshold: alpha >= 1.5%/yr AND |t| > 2. Falsified by |t| < 2 or full explanation by QMJ/HML.

## H2 — The political overlay adds no measurable value
Prediction: "minus political" ablation performs within 0.5pp/yr of full.
**Deliberately a NULL hypothesis I expect to confirm.** Recording it in advance means I cannot
later claim I "found" that the overlay works.

## H3 — Neglect adds nothing beyond quality and value in Sleeve E
Basis: Beard & Sias (1997) found no neglect premium after size adjustment.

## H4 — Tax alpha exceeds security-selection alpha
Prediction: after-tax improvement from lot selection and harvesting exceeds FF5+MOM alpha in
the first three years. **If true, the highest-value part of this project is arithmetic, not
insight.** That is a finding worth publishing.

## H5 — I am overconfident
Prediction: overconfidence ratio > 1.0 across my first 40 scored predictions.

## H6 — Factor IC is weak or absent (added 2026-08-04, docs/13 §2.3)
Prediction: mean rank IC for each component factor is between 0.00 and 0.05, with t-stat < 2 on
a 40-quarter sample. **If IC is absent, any portfolio-level result is construction, not signal**,
and the honest conclusion is to simplify to a factor ETF.

## H7 — LLM extraction features are contaminated pre-cutoff (added 2026-08-04, docs/13 §1)
Prediction: feature IC before the model's training cutoff exceeds post-cutoff IC by > 50%.
Test: alpha-decay test (TICKET-045). **A confirmed contamination is a publishable methodological
finding**, and a rebuttal of the LLM-trading-agent literature's backtests.

---
Amendments: `research/protocol/amendments.md`, dated, with reasons. Never edit in place.
