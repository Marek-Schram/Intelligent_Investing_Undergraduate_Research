"""Narrative generator + honesty validator. TICKET-021.

The part most likely to drift into marketing copy, so constraints are enforced in code.

BANNED_PHRASES = ("positioned to benefit", "expected to", "should continue", "poised for",
  "we believe", "looking ahead", "going forward", "strong conviction", "compelling
  opportunity", "proven track record", "multi-bagger", "next big thing")

generate_narrative(metrics, attribution, contributions, context) -> str. 4-8 sentences:
  1 result vs benchmark (never standalone) · 2 Brinson driver with sector named · 3 since-
  inception excess WITH its CI · 4 factor verdict with t-stat · 5 PBO · 6 process health ·
  7 at least one thing that went wrong. Names best AND worst contributor by ticker.
validate_narrative(text, n_periods) -> list[str] violations. The writer RAISES if non-empty.
    A narrative that fails validation does not get written to disk.
"""

from __future__ import annotations
