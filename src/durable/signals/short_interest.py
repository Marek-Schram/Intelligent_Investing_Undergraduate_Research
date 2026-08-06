"""Short interest and credit signal. docs/10 section 4. TICKET-034.

available_at = publication_date (11+ business days after settlement).
Thresholds by sleeve: Sleeve C >25%, Sleeve E >10%.
Days-to-cover reported alongside SI pct.
Credit widening triggers an Event Report, NOT an automatic sell.
Missing bond data degrades gracefully — absence is not a signal.

Data source: short interest from FINRA/exchange publications, credit spreads from PIT store.
available_at logic: uses publication_date per CLAUDE.md rule.
Spec section: docs/10 §4.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

SI_THRESHOLD_SLEEVE_C = 0.25
SI_THRESHOLD_SLEEVE_E = 0.10
CREDIT_WIDENING_THRESHOLD_BPS = 100  # 100bps widening triggers event report


class Sleeve(Enum):
    C = "C"
    E = "E"


class CreditEventType(Enum):
    WIDENING = "widening"
    NONE = "none"


@dataclass(frozen=True)
class ShortInterestData:
    """Short interest data point."""

    ticker: str
    shares_short: int
    shares_float: int
    adv: float
    publication_date: date

    @property
    def si_pct_float(self) -> float:
        if self.shares_float == 0:
            return 0.0
        return self.shares_short / self.shares_float

    @property
    def days_to_cover(self) -> float:
        if self.adv == 0:
            return float("inf")
        return self.shares_short / self.adv


@dataclass(frozen=True)
class CreditData:
    """Credit spread data for a single issuer."""

    ticker: str
    spread_bps: float
    spread_bps_prior: float | None
    publication_date: date

    @property
    def widening_bps(self) -> float | None:
        if self.spread_bps_prior is None:
            return None
        return self.spread_bps - self.spread_bps_prior


@dataclass(frozen=True)
class ShortInterestSignal:
    """Combined short interest + credit signal."""

    ticker: str
    si_pct_float: float
    days_to_cover: float
    exceeds_threshold: bool
    threshold_used: float
    sleeve: Sleeve
    credit_event: CreditEventType
    credit_widening_bps: float | None
    available_at: date
    event_report_required: bool


def get_si_threshold(sleeve: Sleeve) -> float:
    """Threshold by sleeve — acceptance criterion."""
    if sleeve == Sleeve.E:
        return SI_THRESHOLD_SLEEVE_E
    return SI_THRESHOLD_SLEEVE_C


def check_short_interest(
    data: ShortInterestData,
    sleeve: Sleeve,
) -> tuple[bool, float]:
    """Check if SI exceeds threshold for the given sleeve.

    Returns (exceeds, threshold_used).
    """
    threshold = get_si_threshold(sleeve)
    exceeds = data.si_pct_float > threshold
    return exceeds, threshold


def check_credit_widening(
    credit: CreditData | None,
) -> tuple[CreditEventType, float | None, bool]:
    """Check for credit widening. Missing bond data degrades gracefully.

    Returns (event_type, widening_bps, event_report_required).
    Missing data => NONE event, no report required (absence is not a signal).
    """
    if credit is None:
        return CreditEventType.NONE, None, False

    widening = credit.widening_bps
    if widening is None:
        return CreditEventType.NONE, None, False

    if widening >= CREDIT_WIDENING_THRESHOLD_BPS:
        return CreditEventType.WIDENING, widening, True

    return CreditEventType.NONE, widening, False


def compute_short_interest_signal(
    si_data: ShortInterestData,
    credit_data: CreditData | None,
    sleeve: Sleeve,
) -> ShortInterestSignal:
    """Compute combined short interest + credit signal.

    available_at = publication_date.
    Credit widening triggers Event Report, NOT automatic sell.
    """
    exceeds, threshold = check_short_interest(si_data, sleeve)
    credit_event, widening_bps, event_report = check_credit_widening(credit_data)

    return ShortInterestSignal(
        ticker=si_data.ticker,
        si_pct_float=si_data.si_pct_float,
        days_to_cover=si_data.days_to_cover,
        exceeds_threshold=exceeds,
        threshold_used=threshold,
        sleeve=sleeve,
        credit_event=credit_event,
        credit_widening_bps=widening_bps,
        available_at=si_data.publication_date,
        event_report_required=event_report,
    )
