"""Decision journal. docs/12 section 1. TICKET-038.

Structured record of investment decisions and predictions, designed to surface
overconfidence, hindsight bias, and repeated mistakes.

Empty disconfirming_evidence raises. Confidence required in [50,99] before outcome.
Entries immutable once resolved. Predictions need a resolution date.
Auto-creates entries during rebalance.

Data source: human decisions, portfolio actions.
available_at logic: N/A (research artifact).
Spec section: docs/12 §1.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class EntryType(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    PREDICTION = "prediction"
    REBALANCE = "rebalance"


class Resolution(Enum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    PARTIALLY_CORRECT = "partially_correct"
    UNRESOLVED = "unresolved"
    EXPIRED = "expired"


class JournalValidationError(ValueError):
    """Raised when a journal entry fails validation."""

    pass


@dataclass
class JournalEntry:
    """One decision journal entry. Immutable once resolved."""

    entry_id: str
    entry_date: date
    entry_type: EntryType
    ticker: str | None
    thesis: str
    disconfirming_evidence: str
    confidence: int  # [50, 99]
    resolution_date: date | None = None
    resolution: Resolution = Resolution.UNRESOLVED
    resolution_notes: str = ""
    emotional_state: str = ""
    resolved: bool = False

    def __post_init__(self):
        validate_entry(self)


def validate_entry(entry: JournalEntry) -> None:
    """Validate a journal entry.

    Raises JournalValidationError if:
    - disconfirming_evidence is empty
    - confidence not in [50, 99]
    - prediction has no resolution_date
    """
    if not entry.disconfirming_evidence or not entry.disconfirming_evidence.strip():
        raise JournalValidationError(
            f"Entry {entry.entry_id}: disconfirming_evidence must not be empty"
        )

    if not (50 <= entry.confidence <= 99):
        raise JournalValidationError(
            f"Entry {entry.entry_id}: confidence must be in [50, 99], got {entry.confidence}"
        )

    if entry.entry_type == EntryType.PREDICTION and entry.resolution_date is None:
        raise JournalValidationError(
            f"Entry {entry.entry_id}: predictions require a resolution_date"
        )


def resolve_entry(
    entry: JournalEntry,
    resolution: Resolution,
    notes: str = "",
) -> JournalEntry:
    """Resolve an entry. Raises if already resolved (immutable once resolved)."""
    if entry.resolved:
        raise JournalValidationError(
            f"Entry {entry.entry_id}: already resolved, entries are immutable once resolved"
        )

    entry.resolution = resolution
    entry.resolution_notes = notes
    entry.resolved = True
    return entry


def create_rebalance_entry(
    entry_id: str,
    entry_date: date,
    thesis: str,
    disconfirming_evidence: str,
    confidence: int,
    tickers_added: list[str] | None = None,
    tickers_removed: list[str] | None = None,
) -> JournalEntry:
    """Auto-create a journal entry during rebalance."""
    ticker_str = ""
    if tickers_added:
        ticker_str += f"+{','.join(tickers_added)}"
    if tickers_removed:
        ticker_str += f" -{','.join(tickers_removed)}"

    return JournalEntry(
        entry_id=entry_id,
        entry_date=entry_date,
        entry_type=EntryType.REBALANCE,
        ticker=ticker_str.strip() or None,
        thesis=thesis,
        disconfirming_evidence=disconfirming_evidence,
        confidence=confidence,
    )


def create_prediction_entry(
    entry_id: str,
    entry_date: date,
    ticker: str | None,
    thesis: str,
    disconfirming_evidence: str,
    confidence: int,
    resolution_date: date,
) -> JournalEntry:
    """Create a prediction entry with a resolution date."""
    return JournalEntry(
        entry_id=entry_id,
        entry_date=entry_date,
        entry_type=EntryType.PREDICTION,
        ticker=ticker,
        thesis=thesis,
        disconfirming_evidence=disconfirming_evidence,
        confidence=confidence,
        resolution_date=resolution_date,
    )
