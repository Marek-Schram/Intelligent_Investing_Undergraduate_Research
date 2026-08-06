"""Quarterly rebalance memo. SPEC §9, TICKET-017, TICKET-046.

Data source: proposal, performance stats, bear cases.
available_at logic: N/A (reporting artifact).
Spec section: SPEC §9, docs/07.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date


class MissingBearCaseError(ValueError):
    """Raised when bear_case or falsifiers is empty."""


class MissingMistakeLineError(ValueError):
    """Raised when the mistake line is not present in the memo."""


class PromotionalLanguageError(ValueError):
    """Raised when narrative contains promotional language."""


PROMOTIONAL_PATTERNS = [
    r"\bthe next\s+\w+",
    r"\bmulti-?bagger\b",
    r"\bmoonshot\b",
    r"\brocket\b",
    r"\b10x\b",
    r"\bguaranteed\b",
    r"\bcan't lose\b",
    r"\bsure thing\b",
    r"\bno-?brainer\b",
    r"\bfree money\b",
    r"\bhidden gem\b",
]

NO_BEAR_CASE_CHECKED_FIELDS = [
    "filings",
    "short_interest",
    "credit",
    "insider_activity",
]


@dataclass
class SellEntry:
    """A sell entry in the memo. Every sell names its rule."""

    ticker: str
    sell_rule: str  # Must reference S1-S5
    rationale: str


@dataclass
class BearCase:
    """Bear case for a position. Required per SPEC, TICKET-046.

    Every bear-case claim carries a filing citation; uncited claims are stripped.
    Bear case is copied verbatim into decisions.csv:disconfirming_evidence.
    """

    ticker: str
    bear_text: str
    falsifiers: list[str]  # Exactly three specific observables
    citations: list[str]  # Filing citations — uncited => stripped with warning
    sleeve: str = "C"  # "C" or "E" — determines enforcement level
    checked_sources: list[str] | None = None  # For "no bear case" path


@dataclass
class MemoContent:
    """Complete memo content. SPEC §9."""

    as_of: date
    # Leads with Sleeve C+E vs VTI
    sleeve_c_return: float
    sleeve_e_return: float
    vti_return: float
    period: str  # e.g. "Q3 2024"

    # Performance
    total_return: float
    benchmark_return: float

    # Sells with rules
    sells: list[SellEntry]

    # Buys
    buys: list[str]

    # Bear cases
    bear_cases: list[BearCase]

    # Holdings summary
    n_positions: int
    cash_pct: float

    # Blank mistake line
    mistakes: str = ""

    # 48h time stated
    review_deadline_hours: int = 48

    # Kill criteria status
    kill_criteria: dict = field(default_factory=dict)


def validate_narrative(text: str) -> tuple[bool, str]:
    """Check for promotional language in either direction.

    Returns (is_valid, explanation).
    """
    text_lower = text.lower()
    for pattern in PROMOTIONAL_PATTERNS:
        match = re.search(pattern, text_lower)
        if match:
            return False, f"promotional language detected: '{match.group()}'"
    return True, "clean"


def validate_bear_case(bc: BearCase, sleeve: str | None = None) -> list[str]:
    """Validate a single bear case. Returns issues.

    T-046: every bear-case claim carries a filing citation; uncited claims stripped.
    """
    issues: list[str] = []
    effective_sleeve = sleeve or bc.sleeve

    if not bc.bear_text:
        issues.append(f"Bear case for {bc.ticker} is empty")

    if len(bc.falsifiers) != 3:
        issues.append(
            f"Bear case for {bc.ticker} needs exactly 3 falsifiers, has {len(bc.falsifiers)}"
        )

    if not bc.citations:
        if effective_sleeve == "E":
            issues.append(
                f"Bear case for {bc.ticker} (Sleeve E) has no filing citations — REQUIRED"
            )
        else:
            issues.append(f"Bear case for {bc.ticker} has no filing citations — claims stripped")

    is_valid, explanation = validate_narrative(bc.bear_text)
    if not is_valid:
        issues.append(f"Bear case for {bc.ticker}: {explanation}")

    if bc.bear_text.lower().startswith("no bear case could be constructed"):
        if not bc.checked_sources:
            issues.append(
                f"Bear case for {bc.ticker}: 'no bear case' requires checked_sources "
                f"listing what was examined (need: {NO_BEAR_CASE_CHECKED_FIELDS})"
            )
        else:
            missing = set(NO_BEAR_CASE_CHECKED_FIELDS) - set(bc.checked_sources)
            if missing:
                issues.append(
                    f"Bear case for {bc.ticker}: 'no bear case' missing checks: {sorted(missing)}"
                )

    return issues


def validate_memo(memo: MemoContent) -> list[str]:
    """Validate memo meets all requirements. Returns list of issues."""
    issues = []

    # Leads with Sleeve C+E vs VTI
    if memo.sleeve_c_return is None or memo.vti_return is None:
        issues.append("Must lead with Sleeve C+E vs VTI comparison")

    # Every sell names its rule
    for sell in memo.sells:
        if not sell.sell_rule:
            issues.append(f"Sell of {sell.ticker} does not name its rule")
        elif not any(sell.sell_rule.startswith(f"S{i}") for i in range(1, 6)):
            issues.append(f"Sell rule '{sell.sell_rule}' does not reference S1-S5")

    # Includes the bear case — T-046 enhanced validation
    for bc in memo.bear_cases:
        issues.extend(validate_bear_case(bc))

    # Blank mistake line exists
    if not hasattr(memo, "mistakes"):
        issues.append("Missing blank 'mistake' line")

    # 48h time stated
    if memo.review_deadline_hours != 48:
        issues.append(f"Review deadline must be 48h, got {memo.review_deadline_hours}h")

    return issues


def generate_memo(
    as_of: date,
    sleeve_c_return: float,
    sleeve_e_return: float,
    vti_return: float,
    total_return: float,
    benchmark_return: float,
    sells: list[SellEntry],
    buys: list[str],
    bear_cases: list[BearCase],
    n_positions: int,
    cash_pct: float,
    period: str,
    kill_criteria: dict | None = None,
    sleeve_e_buys: list[str] | None = None,
) -> MemoContent:
    """Generate a rebalance memo. SPEC §9, TICKET-046.

    Raises MissingBearCaseError if:
      - Any Sleeve E buy has no bear case (required)
      - Any bear case has empty text or != 3 falsifiers
    Warns (but allows) Sleeve C buys without bear case.
    Raises PromotionalLanguageError if bear text contains promotional language.
    """
    sleeve_e_set = set(sleeve_e_buys or [])

    # Validate bear cases exist for buys
    bear_tickers = {bc.ticker for bc in bear_cases}
    warnings: list[str] = []

    for buy in buys:
        if buy not in bear_tickers:
            if buy in sleeve_e_set:
                raise MissingBearCaseError(
                    f"Sleeve E buy of {buy} has no bear case. "
                    "Every Sleeve E position REQUIRES a bear case with 3 falsifiers."
                )
            else:
                warnings.append(f"Sleeve C buy of {buy} has no bear case (warned)")

    # Validate each bear case
    for bc in bear_cases:
        if not bc.bear_text:
            raise MissingBearCaseError(f"Bear case text for {bc.ticker} is empty")
        if len(bc.falsifiers) != 3:
            raise MissingBearCaseError(
                f"Bear case for {bc.ticker} needs exactly 3 falsifiers, has {len(bc.falsifiers)}"
            )
        is_valid, explanation = validate_narrative(bc.bear_text)
        if not is_valid:
            raise PromotionalLanguageError(f"Bear case for {bc.ticker}: {explanation}")

    memo = MemoContent(
        as_of=as_of,
        sleeve_c_return=sleeve_c_return,
        sleeve_e_return=sleeve_e_return,
        vti_return=vti_return,
        period=period,
        total_return=total_return,
        benchmark_return=benchmark_return,
        sells=sells,
        buys=buys,
        bear_cases=bear_cases,
        n_positions=n_positions,
        cash_pct=cash_pct,
        mistakes="",  # Blank — human fills post-review
        review_deadline_hours=48,
        kill_criteria=kill_criteria or {},
    )

    issues = validate_memo(memo)
    if issues:
        raise ValueError(f"Memo validation failed: {issues}")

    return memo, warnings


def bear_case_to_disconfirming_evidence(bc: BearCase) -> str:
    """Copy bear case verbatim into decisions.csv:disconfirming_evidence."""
    return bc.bear_text
