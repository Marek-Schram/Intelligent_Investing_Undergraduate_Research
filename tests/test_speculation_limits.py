"""Sleeve E hard limits. TICKET-024/025/029/046. docs/08.

Most of this file's original xfail placeholders described behavior that is already
implemented and tested elsewhere:
  - OTC/pink-sheet rejection, missing-data exclusion, safety-constants-not-config
    -> tests/test_discovery_universe.py
  - price decline never unlocking a tranche
    -> tests/test_tranches.py::test_price_decline_irrelevant_to_t2_gate
  - bear case required for a Sleeve E buy
    -> tests/test_memo.py (TestMissingBearCase, TestBearCaseValidation)

One placeholder is a real, unimplemented gap and is kept below.
"""

from __future__ import annotations

import pytest


@pytest.mark.xfail(reason="TICKET-025: no code path enforces this yet, see docstring")
def test_manipulation_flag_beats_perfect_fundamentals():
    """A perfect durability score with one manipulation flag must still be excluded.
    .claude/rules/speculation-limits.md rule 19: 'Never suppress a manipulation flag because
    fundamentals look good. The flags win.'

    This is currently NOT enforced in code. `discovery/manipulation.py::run_manipulation_screen`
    correctly computes `is_clean`, but the only place that reads it is
    `discovery/dossier.py::render_markdown`, which prints a warning banner -- it never turns
    into an exclusion. There is no function anywhere that combines a discovery score with a
    manipulation result into a single buy-eligibility decision (score.py's `eligible_watchlist`
    / `eligible_position` do not take manipulation into account at all).

    Needs a real fix, not a test: a gate (e.g. in dossier.py or wherever a Sleeve E buy is
    finally decided) that forces `eligible = False` whenever `not manipulation.is_clean`,
    regardless of score. Left as an honest xfail rather than deleted or faked.
    """
    raise NotImplementedError
