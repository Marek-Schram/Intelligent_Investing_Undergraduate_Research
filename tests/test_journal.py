"""Tests for decision journal. TICKET-038."""

from __future__ import annotations

from datetime import date

import pytest

from durable.research.journal import (
    EntryType,
    JournalEntry,
    JournalValidationError,
    Resolution,
    create_prediction_entry,
    create_rebalance_entry,
    resolve_entry,
)


class TestDisconfirmingEvidenceRequired:
    """Empty disconfirming_evidence raises — acceptance criterion."""

    def test_empty_raises(self):
        with pytest.raises(JournalValidationError, match="disconfirming_evidence"):
            JournalEntry(
                entry_id="J001",
                entry_date=date(2025, 6, 1),
                entry_type=EntryType.BUY,
                ticker="AAPL",
                thesis="Strong ecosystem",
                disconfirming_evidence="",
                confidence=70,
            )

    def test_whitespace_only_raises(self):
        with pytest.raises(JournalValidationError):
            JournalEntry(
                entry_id="J002",
                entry_date=date(2025, 6, 1),
                entry_type=EntryType.BUY,
                ticker="AAPL",
                thesis="Test",
                disconfirming_evidence="   ",
                confidence=70,
            )

    def test_valid_disconfirming_passes(self):
        entry = JournalEntry(
            entry_id="J003",
            entry_date=date(2025, 6, 1),
            entry_type=EntryType.BUY,
            ticker="AAPL",
            thesis="Strong ecosystem",
            disconfirming_evidence="Regulatory risk in EU, antitrust",
            confidence=75,
        )
        assert entry.disconfirming_evidence == "Regulatory risk in EU, antitrust"


class TestConfidenceRange:
    """Confidence required in [50,99] before any outcome — acceptance criterion."""

    def test_below_50_raises(self):
        with pytest.raises(JournalValidationError, match="confidence"):
            JournalEntry(
                entry_id="J004",
                entry_date=date(2025, 6, 1),
                entry_type=EntryType.BUY,
                ticker="X",
                thesis="T",
                disconfirming_evidence="D",
                confidence=49,
            )

    def test_above_99_raises(self):
        with pytest.raises(JournalValidationError, match="confidence"):
            JournalEntry(
                entry_id="J005",
                entry_date=date(2025, 6, 1),
                entry_type=EntryType.BUY,
                ticker="X",
                thesis="T",
                disconfirming_evidence="D",
                confidence=100,
            )

    def test_50_valid(self):
        entry = JournalEntry(
            entry_id="J006",
            entry_date=date(2025, 6, 1),
            entry_type=EntryType.HOLD,
            ticker="X",
            thesis="T",
            disconfirming_evidence="D",
            confidence=50,
        )
        assert entry.confidence == 50

    def test_99_valid(self):
        entry = JournalEntry(
            entry_id="J007",
            entry_date=date(2025, 6, 1),
            entry_type=EntryType.HOLD,
            ticker="X",
            thesis="T",
            disconfirming_evidence="D",
            confidence=99,
        )
        assert entry.confidence == 99


class TestImmutableOnceResolved:
    """Entries immutable once resolved — acceptance criterion."""

    def test_resolve_works(self):
        entry = JournalEntry(
            entry_id="J008",
            entry_date=date(2025, 6, 1),
            entry_type=EntryType.BUY,
            ticker="X",
            thesis="T",
            disconfirming_evidence="D",
            confidence=70,
        )
        resolve_entry(entry, Resolution.CORRECT, "Thesis confirmed")
        assert entry.resolved is True
        assert entry.resolution == Resolution.CORRECT

    def test_double_resolve_raises(self):
        entry = JournalEntry(
            entry_id="J009",
            entry_date=date(2025, 6, 1),
            entry_type=EntryType.BUY,
            ticker="X",
            thesis="T",
            disconfirming_evidence="D",
            confidence=70,
        )
        resolve_entry(entry, Resolution.INCORRECT)
        with pytest.raises(JournalValidationError, match="immutable"):
            resolve_entry(entry, Resolution.CORRECT)


class TestPredictionResolutionDate:
    """Predictions need a resolution date — acceptance criterion."""

    def test_prediction_without_date_raises(self):
        with pytest.raises(JournalValidationError, match="resolution_date"):
            JournalEntry(
                entry_id="J010",
                entry_date=date(2025, 6, 1),
                entry_type=EntryType.PREDICTION,
                ticker="SPY",
                thesis="Market up 10%",
                disconfirming_evidence="Recession indicators",
                confidence=60,
                resolution_date=None,
            )

    def test_prediction_with_date_valid(self):
        entry = create_prediction_entry(
            entry_id="J011",
            entry_date=date(2025, 6, 1),
            ticker="SPY",
            thesis="Market up 10%",
            disconfirming_evidence="Yield curve inversion",
            confidence=60,
            resolution_date=date(2026, 6, 1),
        )
        assert entry.resolution_date == date(2026, 6, 1)


class TestAutoCreateDuringRebalance:
    """Auto-creates entries during rebalance — acceptance criterion."""

    def test_rebalance_entry_created(self):
        entry = create_rebalance_entry(
            entry_id="R001",
            entry_date=date(2025, 7, 1),
            thesis="Quarterly rebalance per score changes",
            disconfirming_evidence="Factor IC has been declining",
            confidence=65,
            tickers_added=["NEW1", "NEW2"],
            tickers_removed=["OLD1"],
        )
        assert entry.entry_type == EntryType.REBALANCE
        assert "NEW1" in entry.ticker
        assert "OLD1" in entry.ticker

    def test_non_buy_types_no_resolution_date_ok(self):
        entry = JournalEntry(
            entry_id="J012",
            entry_date=date(2025, 6, 1),
            entry_type=EntryType.SELL,
            ticker="X",
            thesis="Sell rule S3",
            disconfirming_evidence="Thesis may still be intact",
            confidence=80,
        )
        assert entry.resolution_date is None
