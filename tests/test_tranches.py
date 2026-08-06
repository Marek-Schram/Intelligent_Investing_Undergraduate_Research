"""Tests for staged entry tranches. TICKET-029."""

from __future__ import annotations

from datetime import date

import pytest

from durable.discovery.tranche import (
    DOSSIER_SECTIONS,
    Dossier,
    ExitFacts,
    ExitRule,
    TrancheFacts,
    TrancheState,
    exit_rules,
    next_tranche_gate,
    size_tranche,
)


def _state(tranche=1, last_date=date(2025, 1, 1), quarters_at_entry=12, **kw):
    defaults = dict(
        ticker="TEST",
        current_tranche=tranche,
        last_tranche_date=last_date,
        quarters_filed_at_entry=quarters_at_entry,
        current_quarters_filed=quarters_at_entry,
        durability_at_entry=35.0,
        current_durability=35.0,
        current_score=80.0,
    )
    defaults.update(kw)
    return TrancheState(**defaults)


class TestSizeTrancheMinimum:
    """size_tranche returns the MINIMUM of four constraints — acceptance criterion."""

    def test_tranche_fraction_binding(self):
        """When tranche fraction is smallest."""
        result = size_tranche(
            tranche_number=1,
            total_portfolio_value=100_000,  # 0.25% = $250, T1 40% = $100
            adv_60d=50_000,  # 1% = $500
            current_sleeve_e_value=0,
        )
        assert result.amount == pytest.approx(100.0)
        assert result.constraint_binding == "tranche_fraction"

    def test_adv_binding(self):
        """When ADV limit is smallest."""
        result = size_tranche(
            tranche_number=1,
            total_portfolio_value=1_000_000,  # 0.25% = $2500, T1 40% = $1000
            adv_60d=50_000,  # 1% = $500
            current_sleeve_e_value=0,
        )
        assert result.amount == pytest.approx(500.0)
        assert result.constraint_binding == "adv_limit"

    def test_sleeve_remaining_binding(self):
        """When sleeve E budget is almost exhausted."""
        result = size_tranche(
            tranche_number=1,
            total_portfolio_value=1_000_000,
            adv_60d=5_000_000,
            current_sleeve_e_value=19_950,  # Only $50 remaining of $20K
        )
        assert result.amount == pytest.approx(50.0)
        assert result.constraint_binding == "sleeve_remaining"


class TestSubMinimumReturnsZero:
    """Sub-minimum returns 0.0, never rounds up — acceptance criterion."""

    def test_below_broker_minimum_returns_zero(self):
        result = size_tranche(
            tranche_number=1,
            total_portfolio_value=100,  # 0.25% = $0.25, T1 40% = $0.10
            adv_60d=10_000,
        )
        assert result.amount == 0.0
        assert result.constraint_binding == "below_broker_minimum"

    def test_sleeve_exhausted_returns_zero(self):
        result = size_tranche(
            tranche_number=1,
            total_portfolio_value=1_000_000,
            adv_60d=5_000_000,
            current_sleeve_e_value=20_000,  # 2% fully used
        )
        assert result.amount == 0.0


class TestDrawdownDoesNotUnlockT2:
    """50% drawdown with unchanged fundamentals does NOT unlock T2 — acceptance criterion."""

    def test_price_decline_irrelevant_to_t2_gate(self):
        """T2 gate only checks quarters filed and durability, never price."""
        state = _state(tranche=1, last_date=date(2024, 6, 1), quarters_at_entry=12)
        facts = TrancheFacts(
            quarters_filed=12,  # No new quarters filed
            durability=35.0,  # Unchanged
            score=80.0,
        )
        # Even though hypothetically price dropped 50%, T2 doesn't check price
        result = next_tranche_gate(state, facts, as_of=date(2025, 6, 1))
        assert result.eligible is False
        assert "2 additional quarters" in result.explanation

    def test_t2_requires_business_confirmation(self):
        """T2 unlocks only with 2 additional quarters — business confirmation."""
        state = _state(tranche=1, last_date=date(2024, 6, 1), quarters_at_entry=12)
        facts = TrancheFacts(
            quarters_filed=14,  # 2 more quarters
            durability=35.0,
            score=80.0,
        )
        result = next_tranche_gate(state, facts, as_of=date(2025, 6, 1))
        assert result.eligible is True
        assert "T2 gate passed" in result.explanation


class TestScoreCancelsPermanently:
    """Score < 60 cancels permanently — acceptance criterion."""

    def test_score_below_60_cancels(self):
        state = _state(tranche=1, last_date=date(2024, 6, 1))
        facts = TrancheFacts(quarters_filed=14, durability=35.0, score=55.0)
        result = next_tranche_gate(state, facts, as_of=date(2025, 6, 1))
        assert result.eligible is False
        assert state.cancelled is True

    def test_cancelled_state_persists(self):
        """Once cancelled, always cancelled."""
        state = _state(tranche=1, last_date=date(2024, 6, 1))
        state.cancelled = True
        state.cancel_reason = "score 55 < 60"
        facts = TrancheFacts(quarters_filed=20, durability=50.0, score=90.0)
        result = next_tranche_gate(state, facts, as_of=date(2025, 6, 1))
        assert result.eligible is False


class TestE1Graduation:
    """E1 graduation reported as success — acceptance criterion."""

    def test_graduation_is_success(self):
        state = _state()
        facts = ExitFacts(
            market_cap=4e9,
            analyst_count=8,
            score=75,
            durability=40.0,
        )
        result = exit_rules(state, facts)
        assert result.should_exit is True
        assert result.rule == ExitRule.E1_GRADUATION
        assert result.is_success is True
        assert "graduated" in result.explanation

    def test_not_graduation_if_cap_below(self):
        state = _state()
        facts = ExitFacts(
            market_cap=2e9,
            analyst_count=8,
            score=75,
            durability=40.0,
        )
        result = exit_rules(state, facts)
        assert result.rule != ExitRule.E1_GRADUATION


class TestE4ManipulationExitsRegardlessOfPnL:
    """E4 exits regardless of P&L — acceptance criterion."""

    def test_e4_with_profit(self):
        state = _state()
        facts = ExitFacts(score=80, durability=40.0, pnl_pct=0.50)
        result = exit_rules(state, facts, manipulation_flags_triggered=["paid_promotion"])
        assert result.should_exit is True
        assert result.rule == ExitRule.E4_MANIPULATION

    def test_e4_with_loss(self):
        state = _state()
        facts = ExitFacts(score=80, durability=40.0, pnl_pct=-0.30)
        result = exit_rules(state, facts, manipulation_flags_triggered=["social_velocity"])
        assert result.should_exit is True
        assert result.rule == ExitRule.E4_MANIPULATION

    def test_e4_takes_priority_over_graduation(self):
        """Manipulation overrides even graduation conditions."""
        state = _state()
        facts = ExitFacts(
            market_cap=5e9,
            analyst_count=10,
            score=80,
            durability=40.0,
        )
        result = exit_rules(state, facts, manipulation_flags_triggered=["toxic_financing"])
        assert result.rule == ExitRule.E4_MANIPULATION


class TestDossierNineSections:
    """Dossier has all nine sections — acceptance criterion."""

    def test_nine_sections_defined(self):
        assert len(DOSSIER_SECTIONS) == 9

    def test_complete_dossier(self):
        sections = {s: f"content for {s}" for s in DOSSIER_SECTIONS}
        dossier = Dossier(ticker="TEST", sections=sections)
        assert dossier.is_complete is True
        assert dossier.missing_sections == []

    def test_incomplete_dossier(self):
        sections = {"business_description": "A company."}
        dossier = Dossier(ticker="TEST", sections=sections)
        assert dossier.is_complete is False
        assert len(dossier.missing_sections) == 8


class TestMinDaysBetweenTranches:
    def test_too_early(self):
        state = _state(tranche=1, last_date=date(2025, 3, 1))
        facts = TrancheFacts(quarters_filed=14, durability=35.0, score=80.0)
        result = next_tranche_gate(state, facts, as_of=date(2025, 5, 1))
        assert result.eligible is False
        assert "days" in result.explanation

    def test_exactly_90_days(self):
        state = _state(tranche=1, last_date=date(2025, 1, 1), quarters_at_entry=12)
        facts = TrancheFacts(quarters_filed=14, durability=35.0, score=80.0)
        result = next_tranche_gate(state, facts, as_of=date(2025, 4, 1))
        assert result.eligible is True


class TestOtherExitRules:
    def test_e3_score_below_55_twice(self):
        state = _state()
        facts = ExitFacts(score=50, durability=30.0, score_below_55_count=2)
        result = exit_rules(state, facts)
        assert result.should_exit is True
        assert result.rule == ExitRule.E3_SCORE_BELOW_55_TWICE

    def test_e5_liquidity(self):
        state = _state()
        facts = ExitFacts(score=70, durability=35.0, adv_60d=300_000)
        result = exit_rules(state, facts)
        assert result.should_exit is True
        assert result.rule == ExitRule.E5_LIQUIDITY

    def test_no_exit_when_healthy(self):
        state = _state()
        facts = ExitFacts(
            market_cap=1e9,
            analyst_count=2,
            score=80,
            durability=40.0,
            adv_60d=5e6,
        )
        result = exit_rules(state, facts)
        assert result.should_exit is False
