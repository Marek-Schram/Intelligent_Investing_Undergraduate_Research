"""Sleeve E discovery score (0-100). docs/08 section 4. TICKET-028.

Components:
  Durability gate (0-40): must reach >= 30/50 to proceed. If gate fails, score=0.
  Neglect (0-25): from neglect.compute_neglect_score()
  Valuation (0-25): small-cap peer ranking. EV/EBIT > 30 => excluded.
  Quality evidence (0-10): filing-cited only. Uncited claims score 0.
  Overlays (±5): insider purchases and institutional conviction.

Durability gate is checked FIRST. If durability < 30, the candidate is rejected
immediately and no further scoring is performed.

Small-cap peer ranking: rank valuation metrics against peers in the same SIC 2-digit
group within Sleeve E's cap range. Fallback: all Sleeve E eligible names if peer
group has < 5 members.

Data source: durability score, fundamentals, filings from PIT store.
available_at logic: all data filtered via store.as_of(as_of) upstream.
Spec section: docs/08 §4.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


DURABILITY_GATE_MIN = 30
DURABILITY_GATE_MAX_SCORE = 50
DURABILITY_WEIGHT_MAX = 40
NEGLECT_MAX = 25
VALUATION_MAX = 25
QUALITY_MAX = 10
OVERLAY_MAX = 5

EV_EBIT_EXCLUSION_THRESHOLD = 30
MIN_PEER_GROUP_SIZE = 5

WATCHLIST_THRESHOLD = 65
POSITION_THRESHOLD = 75


class GateResult(Enum):
    PASSED = "passed"
    FAILED_DURABILITY = "failed_durability"
    FAILED_VALUATION = "failed_ev_ebit"


@dataclass(frozen=True)
class QualityClaim:
    """A quality claim with its filing citation."""

    claim: str
    cited: bool
    points: int


@dataclass(frozen=True)
class DiscoveryScore:
    """Complete Sleeve E discovery score breakdown."""

    ticker: str
    total: int
    gate_result: GateResult
    durability_sub: int
    neglect_sub: int
    valuation_sub: int
    quality_sub: int
    overlay_sub: int
    quality_claims: list[QualityClaim]
    ev_ebit: float | None = None
    peer_group_size: int = 0
    used_fallback_peers: bool = False

    @property
    def eligible_watchlist(self) -> bool:
        return self.total >= WATCHLIST_THRESHOLD

    @property
    def eligible_position(self) -> bool:
        return self.total >= POSITION_THRESHOLD


def _durability_subscore(durability_raw: float | None) -> tuple[int, GateResult]:
    """Gate + scale durability to 0-40.

    Gate: durability must be >= 30 (out of 50). If gate fails, return (0, FAILED).
    Scale: linearly from 30/50 -> 0/40, 50/50 -> 40/40.
    """
    if durability_raw is None or durability_raw < DURABILITY_GATE_MIN:
        return 0, GateResult.FAILED_DURABILITY

    scaled = int(
        (durability_raw - DURABILITY_GATE_MIN)
        / (DURABILITY_GATE_MAX_SCORE - DURABILITY_GATE_MIN)
        * DURABILITY_WEIGHT_MAX
    )
    return min(scaled, DURABILITY_WEIGHT_MAX), GateResult.PASSED


def _valuation_subscore(
    ev_ebit: float | None,
    peer_ev_ebits: list[float] | None,
) -> tuple[int, bool, int]:
    """Rank EV/EBIT against small-cap peers. Lower is better.

    Returns (score, used_fallback, peer_count).
    EV/EBIT > 30 => excluded (returns 0 with failed gate check handled upstream).
    """
    if ev_ebit is None or peer_ev_ebits is None or len(peer_ev_ebits) == 0:
        return 0, False, 0

    used_fallback = len(peer_ev_ebits) < MIN_PEER_GROUP_SIZE
    peer_count = len(peer_ev_ebits)

    all_values = sorted(peer_ev_ebits + [ev_ebit])
    rank = all_values.index(ev_ebit)
    total = len(all_values)

    percentile = 1.0 - (rank / max(total - 1, 1))
    score = int(percentile * VALUATION_MAX)
    return min(score, VALUATION_MAX), used_fallback, peer_count


def _quality_subscore(claims: list[QualityClaim]) -> int:
    """Only filing-cited claims score. Uncited claims score 0."""
    total = sum(c.points for c in claims if c.cited)
    return min(total, QUALITY_MAX)


def _overlay_subscore(
    insider_purchases_90d: int = 0,
    institutional_conviction_count: int = 0,
) -> int:
    """Insider purchases and institutional conviction. Capped ±5."""
    score = 0
    if insider_purchases_90d >= 3:
        score += 3
    elif insider_purchases_90d >= 1:
        score += 1

    if institutional_conviction_count >= 2:
        score += 2
    elif institutional_conviction_count >= 1:
        score += 1

    return min(score, OVERLAY_MAX)


def compute_discovery_score(
    ticker: str,
    durability_raw: float | None,
    neglect_sub: int = 0,
    ev_ebit: float | None = None,
    peer_ev_ebits: list[float] | None = None,
    quality_claims: list[QualityClaim] | None = None,
    insider_purchases_90d: int = 0,
    institutional_conviction_count: int = 0,
) -> DiscoveryScore:
    """Compute the full Sleeve E discovery score (0-100).

    Durability gate checked FIRST. If it fails, total=0.
    EV/EBIT > 30 => excluded.
    """
    if quality_claims is None:
        quality_claims = []

    durability_sub, gate_result = _durability_subscore(durability_raw)

    if gate_result == GateResult.FAILED_DURABILITY:
        return DiscoveryScore(
            ticker=ticker,
            total=0,
            gate_result=gate_result,
            durability_sub=0,
            neglect_sub=0,
            valuation_sub=0,
            quality_sub=0,
            overlay_sub=0,
            quality_claims=quality_claims,
            ev_ebit=ev_ebit,
        )

    if ev_ebit is not None and ev_ebit > EV_EBIT_EXCLUSION_THRESHOLD:
        return DiscoveryScore(
            ticker=ticker,
            total=0,
            gate_result=GateResult.FAILED_VALUATION,
            durability_sub=durability_sub,
            neglect_sub=0,
            valuation_sub=0,
            quality_sub=0,
            overlay_sub=0,
            quality_claims=quality_claims,
            ev_ebit=ev_ebit,
        )

    valuation_sub, used_fallback, peer_count = _valuation_subscore(ev_ebit, peer_ev_ebits)
    quality_sub = _quality_subscore(quality_claims)
    overlay_sub = _overlay_subscore(insider_purchases_90d, institutional_conviction_count)

    neglect_capped = min(neglect_sub, NEGLECT_MAX)
    total = durability_sub + neglect_capped + valuation_sub + quality_sub + overlay_sub

    return DiscoveryScore(
        ticker=ticker,
        total=total,
        gate_result=GateResult.PASSED,
        durability_sub=durability_sub,
        neglect_sub=neglect_capped,
        valuation_sub=valuation_sub,
        quality_sub=quality_sub,
        overlay_sub=overlay_sub,
        quality_claims=quality_claims,
        ev_ebit=ev_ebit,
        peer_group_size=peer_count,
        used_fallback_peers=used_fallback,
    )
