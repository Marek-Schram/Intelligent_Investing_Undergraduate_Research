---
description: Anti-vanity constraints for generated performance reports.
paths: ["src/durable/reporting/**", "reports/**"]
---

# Rule: Reporting honesty

1. **Benchmark first.** Absolute return always appears beside the benchmark in the same block.
2. **Uncertainty mandatory.** Point estimates ship with a CI when N >= 8; below that print
   `(CI unavailable: N < 8 periods)`.
3. **No cherry-picked windows.** Since-inception, YTD, and trailing 12m — all three, always.
4. **Report residuals.** Brinson interaction and factor residual shown, never redistributed.
5. **Name losses as specifically as gains.** Worst contributor by ticker.
6. **No forward-looking language.**
7. **Never call an insignificant result skill.** A CI crossing zero must be said plainly.
8. **Kill-criteria table on every report** — all six, PASS/WARN/FAIL.
9. **Small-sample banner** until 12 quarters of live data.
10. **Never claim "GIPS-compliant."** Say "GIPS-style time-weighted return."
11. Reporting code must never import `execution/`. A hook blocks it.
12. Report after-tax alongside pre-tax wherever taxes are modeled.
13. Report factor IC alongside portfolio returns — a portfolio can look fine while every
    underlying factor has zero information content.
