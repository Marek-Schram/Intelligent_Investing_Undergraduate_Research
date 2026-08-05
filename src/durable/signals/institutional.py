"""13F institutional ownership signal. docs/10 section 2. TICKET-032.

available_at = filed_at (NOT period_end). Test asserts period_end is never used.
CUSIP-based matching — stable across mergers and ticker changes.
Change classification: new_position, increased, decreased, exited, unchanged.
Managers from config with NO performance field (assert its absence).
Overlay capped ±2.

Data source: 13F filings from PIT store.
available_at logic: 13F filed_at (45 days after quarter end).
Spec section: docs/10 §2.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


OVERLAY_CAP = 2


class ChangeType(Enum):
    NEW_POSITION = "new_position"
    INCREASED = "increased"
    DECREASED = "decreased"
    EXITED = "exited"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class ManagerConfig:
    """Tracked concentrated manager. NO performance field."""

    name: str
    cik: str
    style: str  # e.g. "concentrated_value", "deep_value"

    def __post_init__(self):
        if hasattr(self, "performance"):
            raise AttributeError("ManagerConfig must NOT have a performance field")


@dataclass(frozen=True)
class Holding13F:
    """One 13F holding entry."""

    cusip: str
    ticker: str | None
    shares: int
    value: float
    filed_at: date
    period_end: date  # Stored but NEVER used for available_at


@dataclass(frozen=True)
class OwnershipChange:
    """Change in institutional ownership between filings."""

    manager_name: str
    cusip: str
    ticker: str | None
    change_type: ChangeType
    shares_current: int
    shares_previous: int
    filed_at: date

    @property
    def shares_delta(self) -> int:
        return self.shares_current - self.shares_previous


@dataclass(frozen=True)
class InstitutionalSignal:
    """Aggregated institutional signal for a security."""

    cusip: str
    ticker: str | None
    changes: list[OwnershipChange]
    overlay_score: int
    conviction_manager_count: int
    available_at: date


def classify_change(shares_current: int, shares_previous: int) -> ChangeType:
    """Classify ownership change."""
    if shares_previous == 0 and shares_current > 0:
        return ChangeType.NEW_POSITION
    if shares_current == 0 and shares_previous > 0:
        return ChangeType.EXITED
    if shares_current > shares_previous:
        return ChangeType.INCREASED
    if shares_current < shares_previous:
        return ChangeType.DECREASED
    return ChangeType.UNCHANGED


def compute_ownership_changes(
    current_holdings: list[Holding13F],
    previous_holdings: list[Holding13F],
    manager_name: str,
    filed_at: date,
) -> list[OwnershipChange]:
    """Compute changes between two filing periods for one manager.

    Uses CUSIP-based matching — stable across mergers and ticker changes.
    """
    prev_by_cusip = {h.cusip: h for h in previous_holdings}
    curr_by_cusip = {h.cusip: h for h in current_holdings}

    all_cusips = set(prev_by_cusip.keys()) | set(curr_by_cusip.keys())
    changes = []

    for cusip in all_cusips:
        curr = curr_by_cusip.get(cusip)
        prev = prev_by_cusip.get(cusip)

        shares_current = curr.shares if curr else 0
        shares_previous = prev.shares if prev else 0
        ticker = (curr.ticker if curr else prev.ticker) if (curr or prev) else None

        change_type = classify_change(shares_current, shares_previous)

        changes.append(OwnershipChange(
            manager_name=manager_name,
            cusip=cusip,
            ticker=ticker,
            change_type=change_type,
            shares_current=shares_current,
            shares_previous=shares_previous,
            filed_at=filed_at,
        ))

    return changes


def compute_overlay(
    changes: list[OwnershipChange],
    tracked_managers: list[ManagerConfig],
) -> int:
    """Compute institutional overlay score, capped ±2.

    +1 per tracked manager with new_position or increased.
    -1 per tracked manager with exited or decreased.
    Capped at ±2.
    """
    tracked_names = {m.name for m in tracked_managers}
    score = 0

    for change in changes:
        if change.manager_name not in tracked_names:
            continue
        if change.change_type in (ChangeType.NEW_POSITION, ChangeType.INCREASED):
            score += 1
        elif change.change_type in (ChangeType.EXITED, ChangeType.DECREASED):
            score -= 1

    return max(-OVERLAY_CAP, min(OVERLAY_CAP, score))


def build_institutional_signal(
    cusip: str,
    ticker: str | None,
    changes: list[OwnershipChange],
    tracked_managers: list[ManagerConfig],
    filed_at: date,
) -> InstitutionalSignal:
    """Build the institutional signal. available_at = filed_at."""
    overlay = compute_overlay(changes, tracked_managers)
    conviction_count = sum(
        1 for c in changes
        if c.manager_name in {m.name for m in tracked_managers}
        and c.change_type in (ChangeType.NEW_POSITION, ChangeType.INCREASED)
    )

    return InstitutionalSignal(
        cusip=cusip,
        ticker=ticker,
        changes=changes,
        overlay_score=overlay,
        conviction_manager_count=conviction_count,
        available_at=filed_at,
    )
