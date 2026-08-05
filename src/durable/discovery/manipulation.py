"""Manipulation detection for Sleeve E candidates. docs/08 section 5. TICKET-025.

Any hit => is_clean=False => permanent exclusion. Never let fundamentals override.
Returns ALL flags including passed ones so the dossier can render them.

Data source: corporate actions, filings, social mentions, prices/volume from the PIT store.
available_at logic: all data filtered via store.as_of(as_of) upstream.
Spec section: docs/08 §5.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


TOXIC_FINANCING_TERMS = (
    "variable-rate conversion",
    "variable conversion",
    "equity line",
    "convertible note with variable",
    "floating conversion",
    "death spiral",
    "toxic convert",
    "dilutive financing",
    "at-the-market offering",
)

PROMOTIONAL_8K_TERMS = (
    "multi-bagger",
    "moonshot",
    "the next",
    "guaranteed return",
    "once in a lifetime",
    "explosive growth",
    "to the moon",
    "100x",
    "1000x",
    "retirement stock",
)


@dataclass(frozen=True)
class ManipulationFlag:
    """One manipulation check result."""

    check: str
    triggered: bool
    detail: str = ""


@dataclass(frozen=True)
class ManipulationResult:
    """Full manipulation screen result for a ticker."""

    ticker: str
    as_of: date
    is_clean: bool
    flags: list[ManipulationFlag]

    @property
    def triggered_flags(self) -> list[ManipulationFlag]:
        return [f for f in self.flags if f.triggered]


def check_paid_promotion(
    has_section_17b_disclosure: bool,
    detected_paid_promotion: bool = False,
) -> ManipulationFlag:
    """Section 17(b) disclosure or detected paid promotion."""
    triggered = has_section_17b_disclosure or detected_paid_promotion
    detail = ""
    if has_section_17b_disclosure:
        detail = "Section 17(b) disclosure found"
    elif detected_paid_promotion:
        detail = "paid promotion detected"
    return ManipulationFlag(check="paid_promotion", triggered=triggered, detail=detail)


def check_social_velocity(
    social_mentions_ratio: float | None,
    has_8k_within_3_days: bool = False,
) -> ManipulationFlag:
    """Social velocity >5x normal WITHOUT an 8-K within 3 days.

    If there IS an 8-K within 3 days, the social spike is explained and does NOT fire.
    """
    if social_mentions_ratio is None:
        return ManipulationFlag(check="social_velocity", triggered=False, detail="no data")

    if social_mentions_ratio > 5.0 and not has_8k_within_3_days:
        return ManipulationFlag(
            check="social_velocity",
            triggered=True,
            detail=f"social mentions {social_mentions_ratio:.1f}x normal with no 8-K",
        )
    return ManipulationFlag(
        check="social_velocity",
        triggered=False,
        detail=f"ratio={social_mentions_ratio:.1f}x, 8k={'yes' if has_8k_within_3_days else 'no'}",
    )


def check_volume_price_spike(
    price_change_pct: float | None,
    volume_ratio: float | None,
    has_filing_within_3_days: bool = False,
) -> ManipulationFlag:
    """>30% move on >5x volume with no filing within 3 days."""
    if price_change_pct is None or volume_ratio is None:
        return ManipulationFlag(check="volume_price_spike", triggered=False, detail="no data")

    spike = abs(price_change_pct) > 0.30 and volume_ratio > 5.0 and not has_filing_within_3_days
    detail = f"price_chg={price_change_pct:.1%}, vol_ratio={volume_ratio:.1f}x"
    if has_filing_within_3_days:
        detail += ", filing explains"
    return ManipulationFlag(check="volume_price_spike", triggered=spike, detail=detail)


def check_toxic_financing(filing_text: str | None) -> ManipulationFlag:
    """Toxic financing language in filings (variable-conversion, equity lines, etc.)."""
    if filing_text is None:
        return ManipulationFlag(check="toxic_financing", triggered=False, detail="no filing text")

    text_lower = filing_text.lower()
    found = [term for term in TOXIC_FINANCING_TERMS if term in text_lower]
    triggered = len(found) > 0
    detail = f"found: {', '.join(found)}" if found else "clean"
    return ManipulationFlag(check="toxic_financing", triggered=triggered, detail=detail)


def check_promotional_8k(filing_text: str | None) -> ManipulationFlag:
    """Promotional language in 8-K filings."""
    if filing_text is None:
        return ManipulationFlag(check="promotional_8k", triggered=False, detail="no 8-K text")

    text_lower = filing_text.lower()
    found = [term for term in PROMOTIONAL_8K_TERMS if term in text_lower]
    triggered = len(found) > 0
    detail = f"found: {', '.join(found)}" if found else "clean"
    return ManipulationFlag(check="promotional_8k", triggered=triggered, detail=detail)


def check_litigation_enforcement(
    has_sec_action: bool = False,
    has_class_action: bool = False,
    has_trading_suspension: bool = False,
) -> ManipulationFlag:
    """SEC enforcement, class-action litigation, trading suspension."""
    triggered = has_sec_action or has_class_action or has_trading_suspension
    parts = []
    if has_sec_action:
        parts.append("SEC action")
    if has_class_action:
        parts.append("class action")
    if has_trading_suspension:
        parts.append("trading suspension")
    detail = ", ".join(parts) if parts else "clean"
    return ManipulationFlag(check="litigation_enforcement", triggered=triggered, detail=detail)


def check_distance_to_default(dd: float | None) -> ManipulationFlag:
    """Distance-to-default < 1.5 => flag."""
    if dd is None:
        return ManipulationFlag(
            check="distance_to_default", triggered=False, detail="no DD data"
        )
    triggered = dd < 1.5
    detail = f"DD={dd:.2f}"
    return ManipulationFlag(check="distance_to_default", triggered=triggered, detail=detail)


def check_short_interest(si_pct_float: float | None) -> ManipulationFlag:
    """Short interest > 10% of float => flag."""
    if si_pct_float is None:
        return ManipulationFlag(
            check="short_interest", triggered=False, detail="no SI data"
        )
    triggered = si_pct_float > 0.10
    detail = f"SI={si_pct_float:.1%} of float"
    return ManipulationFlag(check="short_interest", triggered=triggered, detail=detail)


def check_unsolicited_source(from_unsolicited: bool = False) -> ManipulationFlag:
    """Candidate from unsolicited source (social media, DMs, etc.) => permanent exclusion."""
    detail = "unsolicited source" if from_unsolicited else "systematic screen"
    return ManipulationFlag(
        check="unsolicited_source", triggered=from_unsolicited, detail=detail
    )


def run_manipulation_screen(
    ticker: str,
    as_of: date,
    *,
    has_section_17b_disclosure: bool = False,
    detected_paid_promotion: bool = False,
    social_mentions_ratio: float | None = None,
    has_8k_within_3_days: bool = False,
    price_change_pct: float | None = None,
    volume_ratio: float | None = None,
    has_filing_within_3_days: bool = False,
    filing_text_for_toxic: str | None = None,
    filing_text_8k: str | None = None,
    has_sec_action: bool = False,
    has_class_action: bool = False,
    has_trading_suspension: bool = False,
    distance_to_default: float | None = None,
    si_pct_float: float | None = None,
    from_unsolicited: bool = False,
) -> ManipulationResult:
    """Run all manipulation checks. Any hit => is_clean=False.

    Returns all flags including passed ones (for dossier rendering).
    """
    flags = [
        check_paid_promotion(has_section_17b_disclosure, detected_paid_promotion),
        check_social_velocity(social_mentions_ratio, has_8k_within_3_days),
        check_volume_price_spike(price_change_pct, volume_ratio, has_filing_within_3_days),
        check_toxic_financing(filing_text_for_toxic),
        check_promotional_8k(filing_text_8k),
        check_litigation_enforcement(has_sec_action, has_class_action, has_trading_suspension),
        check_distance_to_default(distance_to_default),
        check_short_interest(si_pct_float),
        check_unsolicited_source(from_unsolicited),
    ]

    is_clean = not any(f.triggered for f in flags)
    return ManipulationResult(ticker=ticker, as_of=as_of, is_clean=is_clean, flags=flags)
