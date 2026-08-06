"""Tests for 13F institutional signal. TICKET-032."""

from __future__ import annotations

from datetime import date

from durable.signals.institutional import (
    OVERLAY_CAP,
    ChangeType,
    Holding13F,
    ManagerConfig,
    OwnershipChange,
    build_institutional_signal,
    classify_change,
    compute_overlay,
    compute_ownership_changes,
)

FILED_AT = date(2025, 5, 15)
PERIOD_END = date(2025, 3, 31)


class TestAvailableAtFiledAt:
    """available_at = filed_at (test asserts period_end never used) — acceptance criterion."""

    def test_signal_uses_filed_at(self):
        signal = build_institutional_signal(
            cusip="12345678",
            ticker="TEST",
            changes=[],
            tracked_managers=[],
            filed_at=FILED_AT,
        )
        assert signal.available_at == FILED_AT
        assert signal.available_at != PERIOD_END

    def test_holding_stores_both_but_signal_uses_filed(self):
        """period_end stored on Holding13F but never flows to available_at."""
        holding = Holding13F(
            cusip="12345678",
            ticker="TEST",
            shares=1000,
            value=50000,
            filed_at=FILED_AT,
            period_end=PERIOD_END,
        )
        assert holding.period_end == PERIOD_END
        assert holding.filed_at == FILED_AT


class TestCUSIPMatching:
    """CUSIP-based matching stable across mergers — acceptance criterion."""

    def test_matches_by_cusip_not_ticker(self):
        """Same CUSIP, different ticker (name change) still matches."""
        prev = [Holding13F("12345678", "OLD_TICKER", 1000, 50000, date(2025, 2, 15), PERIOD_END)]
        curr = [Holding13F("12345678", "NEW_TICKER", 1500, 75000, FILED_AT, PERIOD_END)]

        changes = compute_ownership_changes(curr, prev, "ManagerA", FILED_AT)
        assert len(changes) == 1
        assert changes[0].change_type == ChangeType.INCREASED
        assert changes[0].cusip == "12345678"

    def test_different_cusip_different_security(self):
        prev = [Holding13F("11111111", "AAAA", 1000, 50000, date(2025, 2, 15), PERIOD_END)]
        curr = [Holding13F("22222222", "BBBB", 1000, 50000, FILED_AT, PERIOD_END)]

        changes = compute_ownership_changes(curr, prev, "ManagerA", FILED_AT)
        assert len(changes) == 2
        types = {c.change_type for c in changes}
        assert ChangeType.NEW_POSITION in types
        assert ChangeType.EXITED in types


class TestChangeClassification:
    """Change classification — acceptance criterion."""

    def test_new_position(self):
        assert classify_change(1000, 0) == ChangeType.NEW_POSITION

    def test_increased(self):
        assert classify_change(1500, 1000) == ChangeType.INCREASED

    def test_decreased(self):
        assert classify_change(500, 1000) == ChangeType.DECREASED

    def test_exited(self):
        assert classify_change(0, 1000) == ChangeType.EXITED

    def test_unchanged(self):
        assert classify_change(1000, 1000) == ChangeType.UNCHANGED


class TestManagerConfigNoPerformance:
    """Managers from config with NO performance field — acceptance criterion."""

    def test_no_performance_field(self):
        mgr = ManagerConfig(name="Buffett", cik="0001067983", style="concentrated_value")
        assert not hasattr(mgr, "performance")

    def test_config_fields(self):
        mgr = ManagerConfig(name="Klarman", cik="0000000000", style="deep_value")
        assert mgr.name == "Klarman"
        assert mgr.style == "deep_value"


class TestOverlayCapped:
    """Overlay capped ±2 — acceptance criterion."""

    def test_cap_positive(self):
        managers = [
            ManagerConfig("A", "001", "value"),
            ManagerConfig("B", "002", "value"),
            ManagerConfig("C", "003", "value"),
        ]
        changes = [
            OwnershipChange("A", "X", "T", ChangeType.NEW_POSITION, 1000, 0, FILED_AT),
            OwnershipChange("B", "X", "T", ChangeType.INCREASED, 2000, 1000, FILED_AT),
            OwnershipChange("C", "X", "T", ChangeType.NEW_POSITION, 500, 0, FILED_AT),
        ]
        overlay = compute_overlay(changes, managers)
        assert overlay == OVERLAY_CAP  # 3 capped to 2

    def test_cap_negative(self):
        managers = [
            ManagerConfig("A", "001", "value"),
            ManagerConfig("B", "002", "value"),
            ManagerConfig("C", "003", "value"),
        ]
        changes = [
            OwnershipChange("A", "X", "T", ChangeType.EXITED, 0, 1000, FILED_AT),
            OwnershipChange("B", "X", "T", ChangeType.DECREASED, 500, 2000, FILED_AT),
            OwnershipChange("C", "X", "T", ChangeType.EXITED, 0, 500, FILED_AT),
        ]
        overlay = compute_overlay(changes, managers)
        assert overlay == -OVERLAY_CAP  # -3 capped to -2

    def test_within_cap_unchanged(self):
        managers = [ManagerConfig("A", "001", "value")]
        changes = [
            OwnershipChange("A", "X", "T", ChangeType.NEW_POSITION, 1000, 0, FILED_AT),
        ]
        overlay = compute_overlay(changes, managers)
        assert overlay == 1

    def test_untracked_manager_ignored(self):
        managers = [ManagerConfig("Tracked", "001", "value")]
        changes = [
            OwnershipChange("Unknown", "X", "T", ChangeType.NEW_POSITION, 5000, 0, FILED_AT),
        ]
        overlay = compute_overlay(changes, managers)
        assert overlay == 0


class TestConvictionCount:
    def test_counts_new_and_increased(self):
        managers = [
            ManagerConfig("A", "001", "value"),
            ManagerConfig("B", "002", "value"),
        ]
        changes = [
            OwnershipChange("A", "X", "T", ChangeType.NEW_POSITION, 1000, 0, FILED_AT),
            OwnershipChange("B", "X", "T", ChangeType.INCREASED, 2000, 1000, FILED_AT),
        ]
        signal = build_institutional_signal("X", "T", changes, managers, FILED_AT)
        assert signal.conviction_manager_count == 2
