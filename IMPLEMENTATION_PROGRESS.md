# Implementation Progress

This file is a snapshot, not a plan — `specs/BUILD_TICKETS.md` is the source of truth for what's
left to build. Update the numbers below when they drift, don't let this become a session log.

**As of 2026-08-06:** 952 tests passing, 1 xfailed.

## The one open xfail

`tests/test_speculation_limits.py::test_manipulation_flag_beats_perfect_fundamentals` —
`.claude/rules/speculation-limits.md` rule 19 ("the flags win") is not code-enforced. Nothing
combines a discovery score with `discovery/manipulation.py`'s `is_clean` into a single buy
eligibility decision; `dossier.py` only prints a warning banner. See the test's docstring for
what a real fix needs to do.

## What's implemented and wired in

Core scoring/ranking/backtest pipeline (durability, valuation, momentum, overlays), the PIT
data store and leakage firewall, CPCV/PBO validation, Sleeve E discovery (universe, manipulation,
tranches, dossiers), the tax engine (lots, wash sales, harvesting, after-tax), reporting, and
the execution proposal path — including no-trade-band weight targeting
(`portfolio/construct.py`), sequenced sell-first/cost-reserved order sizing
(`execution/sequencer.py`), and Almgren-Chriss transaction costs in the backtest engine
(`backtest/costs.py`, `backtest/impact.py`).

## What's genuinely unbuilt (not bugs — undone work)

- No real broker connectivity — `submit.py` always dry-runs. Deliberately deferred; needs its
  own careful ticket per CLAUDE.md non-negotiable #4.
- Sector/SIC, exchange listing, public float, analyst coverage, filing full-text are unpopulated
  in ingestion — several factors run on documented conservative fallbacks until real sources
  are wired in.
- No cash/NAV balance table — a first-ever proposal can't size share counts; sequencing assumes
  `cash_on_hand = $0` per rebalance (see `execution/propose.py::build_proposal` docstring).
- `data/universe.py`'s ingest seed is a hardcoded ticker list, not a real point-in-time
  index-constituent source.
- Performance reports (quarterly/pulse/annual) can't run yet — no benchmark-return,
  holdings-count, turnover, or kill-criteria pipeline feeds them. The CLI correctly refuses to
  fabricate output rather than faking it.
