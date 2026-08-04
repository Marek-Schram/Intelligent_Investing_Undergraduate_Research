---
description: Scientific integrity constraints for research outputs.
paths: ["research/**", "src/durable/research/**", "reports/research/**"]
---

# Rule: Research integrity

1. **Preregister before testing.** Hypotheses committed to research/protocol/preregistration.md
   BEFORE the test runs. A hypothesis written after seeing results is a description.
2. **Log every run** to reports/experiment_log.csv — including failures and abandoned ideas.
   The trial count feeds Deflated Sharpe and PBO. Omitting runs inflates both.
3. **Record contradicting evidence.** claims.csv has `contradicted_by` and it must be populated.
   The neglect premium, small-cap premium, and 13F cloning ALL have contradicting studies.
4. **Confidence stated before outcome.** Journal entries immutable once resolved.
5. **`disconfirming_evidence` may not be empty.** Use the `adversarial-review` skill to
   generate the bear case if you are struggling to articulate it.
6. **Limitations written before results exist.** May grow, never shrink.
7. **Reproducibility**: pin commit, snapshot IDs, config hash, seeds, LLM model and prompt
   versions. `make reproduce COMMIT=<hash>` must regenerate byte-identical output.
8. **Never present a null result as failure.**
9. Never use "proves", "confirms", or "demonstrates" for |t| < 2.
10. **No automated strategy or factor generation.** Tools that mine thousands of candidate
    factors make the trial count unknowable and preregistration meaningless (docs/13 §3).
