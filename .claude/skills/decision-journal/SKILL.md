---
name: decision-journal
description: Record an investment decision with a falsifiable prediction and confidence, or score past predictions for calibration.
---

# Decision journal

Read `docs/12 §2`. This may be the most valuable research output here — returns take a decade
to become significant, calibration takes about a year.

## Recording
- `prediction` — falsifiable, with a horizon. "ROIC stays above 12% through FY2027", not "good company".
- `confidence` — 50-99, stated BEFORE the outcome is known. Non-negotiable.
- `reasoning` — 3-5 sentences in the user's own words.
- `key_assumption` — the one thing that must hold.
- `disconfirming_evidence` — **may not be empty.** If the user struggles, run the
  `adversarial-review` skill and use the bear case verbatim.
- `emotional_state` — calm / excited / anxious / rushed / frustrated.

Immutable once the outcome is known. Never backfill a confidence number.

## Scoring
Brier score (0.25 = always saying 50%) · calibration curve with bin counts, sparse bins flagged
not smoothed · overconfidence ratio (mean confidence / hit rate; >1.0 is the common result) ·
discrimination · **calibration by emotional state** — the finding that changes behavior ·
override performance vs the system, cross-referenced with reports/overrides.md.

## Always say
~20 decisions a year means ~3 years for confident conclusions. State the sample size. But the
process of writing a falsifiable prediction before acting is itself the intervention — it
improves decisions immediately, whether or not enough get scored. Report overconfidence plainly.
