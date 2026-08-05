"""Tests for short interest + credit signal. TICKET-034."""

from __future__ import annotations

from datetime import date

import pytest

from durable.signals.short_interest import (
    CREDIT_WIDENING_THRESHOLD_BPS,
    CreditData,
    CreditEventType,
    SI_THRESHOLD_SLEEVE_C,
    SI_THRESHOLD_SLEEVE_E,
    ShortInterestData,
    ShortInterestSignal,
    Sleeve,
    check_credit_widening,
    check_short_interest,
    compute_short_interest_signal,
    get_si_threshold,
)


PUB_DATE = date(2025, 6, 15)


def _si_data(shares_short=500_000, shares_float=5_000_000, adv=200_000):
    return ShortInterestData(
        ticker="TEST",
        shares_short=shares_short,
        shares_float=shares_float,
        adv=adv,
        publication_date=PUB_DATE,
    )


class TestAvailableAtPublicationDate:
    """available_at = publication_date — acceptance criterion."""

    def test_signal_uses_publication_date(self):
        si = _si_data()
        signal = compute_short_interest_signal(si, None, Sleeve.C)
        assert signal.available_at == PUB_DATE


class TestThresholdsBySleeve:
    """Thresholds by sleeve — acceptance criterion."""

    def test_sleeve_c_threshold_25pct(self):
        assert SI_THRESHOLD_SLEEVE_C == 0.25
        assert get_si_threshold(Sleeve.C) == 0.25

    def test_sleeve_e_threshold_10pct(self):
        assert SI_THRESHOLD_SLEEVE_E == 0.10
        assert get_si_threshold(Sleeve.E) == 0.10

    def test_exceeds_sleeve_c(self):
        si = _si_data(shares_short=1_500_000, shares_float=5_000_000)  # 30%
        exceeds, _ = check_short_interest(si, Sleeve.C)
        assert exceeds is True

    def test_below_sleeve_c(self):
        si = _si_data(shares_short=1_000_000, shares_float=5_000_000)  # 20%
        exceeds, _ = check_short_interest(si, Sleeve.C)
        assert exceeds is False

    def test_exceeds_sleeve_e(self):
        si = _si_data(shares_short=600_000, shares_float=5_000_000)  # 12%
        exceeds, _ = check_short_interest(si, Sleeve.E)
        assert exceeds is True

    def test_below_sleeve_e(self):
        si = _si_data(shares_short=400_000, shares_float=5_000_000)  # 8%
        exceeds, _ = check_short_interest(si, Sleeve.E)
        assert exceeds is False


class TestDaysToCover:
    """Days-to-cover reported — acceptance criterion."""

    def test_days_to_cover_calculated(self):
        si = _si_data(shares_short=1_000_000, adv=200_000)
        assert si.days_to_cover == pytest.approx(5.0)

    def test_days_to_cover_in_signal(self):
        si = _si_data(shares_short=1_000_000, adv=200_000)
        signal = compute_short_interest_signal(si, None, Sleeve.C)
        assert signal.days_to_cover == pytest.approx(5.0)

    def test_zero_adv_infinite(self):
        si = _si_data(adv=0)
        assert si.days_to_cover == float("inf")


class TestCreditWideningEventReport:
    """Credit widening triggers Event Report NOT automatic sell — acceptance criterion."""

    def test_widening_triggers_event_report(self):
        credit = CreditData(
            ticker="TEST", spread_bps=250, spread_bps_prior=100,
            publication_date=PUB_DATE,
        )
        event, widening, report_required = check_credit_widening(credit)
        assert event == CreditEventType.WIDENING
        assert widening == 150
        assert report_required is True

    def test_signal_marks_event_report_not_sell(self):
        """Event report, NOT automatic sell."""
        si = _si_data()
        credit = CreditData(
            ticker="TEST", spread_bps=300, spread_bps_prior=100,
            publication_date=PUB_DATE,
        )
        signal = compute_short_interest_signal(si, credit, Sleeve.C)
        assert signal.event_report_required is True
        # No "should_sell" field — it's an event report, not a sell signal
        assert not hasattr(signal, "should_sell")

    def test_small_widening_no_event(self):
        credit = CreditData(
            ticker="TEST", spread_bps=150, spread_bps_prior=100,
            publication_date=PUB_DATE,
        )
        event, widening, report_required = check_credit_widening(credit)
        assert event == CreditEventType.NONE
        assert report_required is False


class TestMissingBondDataGraceful:
    """Missing bond data degrades gracefully — acceptance criterion."""

    def test_none_credit_no_signal(self):
        """Absence is not a signal."""
        event, widening, report = check_credit_widening(None)
        assert event == CreditEventType.NONE
        assert widening is None
        assert report is False

    def test_no_prior_spread_graceful(self):
        credit = CreditData(
            ticker="TEST", spread_bps=200, spread_bps_prior=None,
            publication_date=PUB_DATE,
        )
        event, widening, report = check_credit_widening(credit)
        assert event == CreditEventType.NONE
        assert report is False

    def test_signal_works_without_credit(self):
        si = _si_data()
        signal = compute_short_interest_signal(si, None, Sleeve.E)
        assert signal.credit_event == CreditEventType.NONE
        assert signal.credit_widening_bps is None


class TestSIPctFloat:
    def test_calculation(self):
        si = _si_data(shares_short=500_000, shares_float=5_000_000)
        assert si.si_pct_float == pytest.approx(0.10)

    def test_zero_float(self):
        si = _si_data(shares_float=0)
        assert si.si_pct_float == 0.0
