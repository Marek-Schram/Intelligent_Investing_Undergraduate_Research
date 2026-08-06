"""Neglect score for Sleeve E candidates. docs/08 section 4. TICKET-026.

The neglect premium is CONTESTED. Arbel & Strebel (1982) found low-coverage firms earned excess
returns; Beard & Sias (1997) found NO premium after size adjustment. Neglect is a place to look,
never a reason to buy.

Scoring (0-25):
  - Analyst count (0-8):  0 analysts=8, 1=6, 2=4, 3=2, >=4=0
  - Institutional ownership pct (0-7): <10%=7, <20%=5, <30%=3, <40%=1, >=40%=0
  - Media mentions normalized by cap (0-5): bottom decile=5, 2nd=3, 3rd=1, else=0
  - No sell-side initiation in 24 months (0-5): True=5, False=0

13F available_at = filed_at (NOT period_end).

Data source: analyst coverage counts, 13F institutional ownership, media mentions from PIT store.
available_at logic: 13F uses filed_at per CLAUDE.md rule.
Spec section: docs/08 §4.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

MAX_NEGLECT_SCORE = 25


@dataclass(frozen=True)
class NeglectInputs:
    """Raw inputs for the neglect score — returned for transparency."""

    analyst_count: int | None
    institutional_ownership_pct: float | None
    media_mentions_decile: int | None
    has_sell_side_initiation_24m: bool | None
    filed_at: date | None = None


@dataclass(frozen=True)
class NeglectResult:
    """Neglect score with raw inputs and component breakdown."""

    ticker: str
    score: int
    capped_score: int
    analyst_sub: int
    institutional_sub: int
    media_sub: int
    initiation_sub: int
    inputs: NeglectInputs


def _score_analyst_count(count: int | None) -> int:
    """0 analysts=8, 1=6, 2=4, 3=2, >=4=0."""
    if count is None:
        return 0
    if count == 0:
        return 8
    if count == 1:
        return 6
    if count == 2:
        return 4
    if count == 3:
        return 2
    return 0


def _score_institutional_ownership(pct: float | None) -> int:
    """<10%=7, <20%=5, <30%=3, <40%=1, >=40%=0."""
    if pct is None:
        return 0
    if pct < 0.10:
        return 7
    if pct < 0.20:
        return 5
    if pct < 0.30:
        return 3
    if pct < 0.40:
        return 1
    return 0


def _score_media_mentions(decile: int | None) -> int:
    """Bottom decile=5, 2nd=3, 3rd=1, else=0. Decile 1=lowest."""
    if decile is None:
        return 0
    if decile == 1:
        return 5
    if decile == 2:
        return 3
    if decile == 3:
        return 1
    return 0


def _score_initiation(has_initiation_24m: bool | None) -> int:
    """No sell-side initiation in 24 months = 5."""
    if has_initiation_24m is None:
        return 0
    return 0 if has_initiation_24m else 5


def compute_neglect_score(
    ticker: str,
    analyst_count: int | None = None,
    institutional_ownership_pct: float | None = None,
    media_mentions_decile: int | None = None,
    has_sell_side_initiation_24m: bool | None = None,
    filed_at: date | None = None,
) -> NeglectResult:
    """Compute neglect sub-score (0-25, capped at 25).

    Raw inputs are returned for dossier transparency.
    """
    analyst_sub = _score_analyst_count(analyst_count)
    institutional_sub = _score_institutional_ownership(institutional_ownership_pct)
    media_sub = _score_media_mentions(media_mentions_decile)
    initiation_sub = _score_initiation(has_sell_side_initiation_24m)

    raw_score = analyst_sub + institutional_sub + media_sub + initiation_sub
    capped = min(raw_score, MAX_NEGLECT_SCORE)

    inputs = NeglectInputs(
        analyst_count=analyst_count,
        institutional_ownership_pct=institutional_ownership_pct,
        media_mentions_decile=media_mentions_decile,
        has_sell_side_initiation_24m=has_sell_side_initiation_24m,
        filed_at=filed_at,
    )

    return NeglectResult(
        ticker=ticker,
        score=raw_score,
        capped_score=capped,
        analyst_sub=analyst_sub,
        institutional_sub=institutional_sub,
        media_sub=media_sub,
        initiation_sub=initiation_sub,
        inputs=inputs,
    )
