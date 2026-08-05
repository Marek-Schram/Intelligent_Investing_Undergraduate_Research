"""Tests for manipulation detection. TICKET-025."""

from __future__ import annotations

from datetime import date

import pytest

from durable.discovery.manipulation import (
    ManipulationFlag,
    ManipulationResult,
    check_distance_to_default,
    check_litigation_enforcement,
    check_paid_promotion,
    check_promotional_8k,
    check_short_interest,
    check_social_velocity,
    check_toxic_financing,
    check_unsolicited_source,
    check_volume_price_spike,
    run_manipulation_screen,
)


AS_OF = date(2025, 6, 15)


class TestAnyHitMeansNotClean:
    """Any single flag => is_clean=False — acceptance criterion."""

    def test_clean_when_all_pass(self):
        result = run_manipulation_screen("GOOD", AS_OF)
        assert result.is_clean is True
        assert result.triggered_flags == []

    def test_single_flag_makes_not_clean(self):
        result = run_manipulation_screen("BAD", AS_OF, has_sec_action=True)
        assert result.is_clean is False
        assert len(result.triggered_flags) == 1

    def test_multiple_flags_all_reported(self):
        result = run_manipulation_screen(
            "AWFUL", AS_OF,
            has_sec_action=True,
            detected_paid_promotion=True,
            si_pct_float=0.15,
        )
        assert result.is_clean is False
        assert len(result.triggered_flags) == 3


class TestReturnsAllFlags:
    """Returns all flags including passed ones — acceptance criterion."""

    def test_all_nine_checks_returned(self):
        result = run_manipulation_screen("TEST", AS_OF)
        assert len(result.flags) == 9

    def test_passed_flags_included(self):
        result = run_manipulation_screen("GOOD", AS_OF, has_sec_action=True)
        passed = [f for f in result.flags if not f.triggered]
        assert len(passed) == 8
        triggered = [f for f in result.flags if f.triggered]
        assert len(triggered) == 1


class TestToxicFinancing:
    """Toxic financing language caught — acceptance criterion."""

    def test_variable_conversion_detected(self):
        text = "The company entered a variable-rate conversion note agreement."
        flag = check_toxic_financing(text)
        assert flag.triggered is True
        assert "variable-rate conversion" in flag.detail

    def test_equity_line_detected(self):
        text = "Signed an equity line of credit facility with investors."
        flag = check_toxic_financing(text)
        assert flag.triggered is True

    def test_clean_filing(self):
        text = "Revenue grew 15% year over year driven by organic growth."
        flag = check_toxic_financing(text)
        assert flag.triggered is False

    def test_none_text_not_triggered(self):
        flag = check_toxic_financing(None)
        assert flag.triggered is False

    def test_case_insensitive(self):
        text = "The EQUITY LINE agreement was finalized."
        flag = check_toxic_financing(text)
        assert flag.triggered is True


class TestSocialVelocity:
    """Social velocity does NOT fire alongside an 8-K — acceptance criterion."""

    def test_high_velocity_no_8k_fires(self):
        flag = check_social_velocity(6.0, has_8k_within_3_days=False)
        assert flag.triggered is True

    def test_high_velocity_with_8k_does_not_fire(self):
        """Critical: 8-K explains the spike, so it does NOT fire."""
        flag = check_social_velocity(10.0, has_8k_within_3_days=True)
        assert flag.triggered is False

    def test_low_velocity_no_fire(self):
        flag = check_social_velocity(3.0, has_8k_within_3_days=False)
        assert flag.triggered is False

    def test_exactly_5x_does_not_fire(self):
        """Must be >5x, not >=5x."""
        flag = check_social_velocity(5.0, has_8k_within_3_days=False)
        assert flag.triggered is False

    def test_none_ratio_no_fire(self):
        flag = check_social_velocity(None)
        assert flag.triggered is False


class TestPerfectFundamentalsStillExcluded:
    """Perfect fundamentals + one flag still excluded — acceptance criterion."""

    def test_great_company_with_promotion_excluded(self):
        """Even if every other check passes, one triggered flag => not clean."""
        result = run_manipulation_screen(
            "PERFECT", AS_OF,
            detected_paid_promotion=True,
        )
        assert result.is_clean is False

    def test_great_company_with_unsolicited_source(self):
        result = run_manipulation_screen(
            "PERFECT", AS_OF,
            from_unsolicited=True,
        )
        assert result.is_clean is False


class TestVolumePriceSpike:
    def test_big_move_big_volume_no_filing(self):
        flag = check_volume_price_spike(0.35, 6.0, has_filing_within_3_days=False)
        assert flag.triggered is True

    def test_big_move_big_volume_with_filing_ok(self):
        flag = check_volume_price_spike(0.35, 6.0, has_filing_within_3_days=True)
        assert flag.triggered is False

    def test_small_move_big_volume_ok(self):
        flag = check_volume_price_spike(0.10, 8.0, has_filing_within_3_days=False)
        assert flag.triggered is False

    def test_big_move_low_volume_ok(self):
        flag = check_volume_price_spike(0.40, 3.0, has_filing_within_3_days=False)
        assert flag.triggered is False

    def test_negative_price_change_also_detected(self):
        """Drop of >30% also triggers (abs value used)."""
        flag = check_volume_price_spike(-0.40, 6.0, has_filing_within_3_days=False)
        assert flag.triggered is True


class TestPromotional8K:
    def test_moonshot_language_detected(self):
        flag = check_promotional_8k("This is a moonshot opportunity for investors.")
        assert flag.triggered is True

    def test_normal_8k_clean(self):
        flag = check_promotional_8k("The company reported quarterly earnings above consensus.")
        assert flag.triggered is False


class TestLitigationEnforcement:
    def test_sec_action(self):
        flag = check_litigation_enforcement(has_sec_action=True)
        assert flag.triggered is True

    def test_trading_suspension(self):
        flag = check_litigation_enforcement(has_trading_suspension=True)
        assert flag.triggered is True

    def test_all_clear(self):
        flag = check_litigation_enforcement()
        assert flag.triggered is False


class TestDistanceToDefault:
    def test_low_dd_triggers(self):
        flag = check_distance_to_default(1.0)
        assert flag.triggered is True

    def test_high_dd_ok(self):
        flag = check_distance_to_default(3.0)
        assert flag.triggered is False

    def test_boundary_1_5_not_triggered(self):
        """DD=1.5 is NOT < 1.5, so it passes."""
        flag = check_distance_to_default(1.5)
        assert flag.triggered is False


class TestShortInterest:
    def test_high_si_triggers(self):
        flag = check_short_interest(0.15)
        assert flag.triggered is True

    def test_low_si_ok(self):
        flag = check_short_interest(0.05)
        assert flag.triggered is False

    def test_boundary_10pct_not_triggered(self):
        """SI=10% is NOT > 10%, so it passes."""
        flag = check_short_interest(0.10)
        assert flag.triggered is False


class TestUnsolicitedSource:
    def test_unsolicited_triggers(self):
        flag = check_unsolicited_source(from_unsolicited=True)
        assert flag.triggered is True

    def test_systematic_ok(self):
        flag = check_unsolicited_source(from_unsolicited=False)
        assert flag.triggered is False
