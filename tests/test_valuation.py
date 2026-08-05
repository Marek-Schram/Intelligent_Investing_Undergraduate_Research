"""Tests for valuation score. TICKET-007. Hand-computed fixtures."""

from __future__ import annotations

import math

import pytest

from durable.factors.valuation import (
    ev_ebit_score,
    fcf_yield_score,
    implied_growth,
    reverse_dcf_gap,
    reverse_dcf_score,
    shareholder_yield_score,
    valuation_score,
)


class TestImpliedGrowth:
    def test_round_trip(self):
        """Implied growth round-trips within 0.1% — acceptance criterion."""
        # Build an EV from known inputs: g=5%, FCF=100, WACC=10%, TV growth=2.5%
        g = 0.05
        fcf_0 = 100.0
        wacc = 0.10
        g_term = 0.025

        pv_fcf = sum(fcf_0 * (1 + g) ** t / (1 + wacc) ** t for t in range(1, 11))
        fcf_10 = fcf_0 * (1 + g) ** 10
        tv = fcf_10 * (1 + g_term) / (wacc - g_term)
        pv_tv = tv / (1 + wacc) ** 10

        ev = pv_fcf + pv_tv

        # Now solve backwards
        result = implied_growth(ev, fcf_0, wacc, g_term)
        assert abs(result - g) < 0.001, f"Expected {g}, got {result}"

    def test_non_convergence_returns_nan(self):
        """Non-convergence returns NaN, never 0.0."""
        # Negative EV should not converge
        result = implied_growth(-100, 50, 0.10)
        assert math.isnan(result)

    def test_zero_fcf_returns_nan(self):
        result = implied_growth(1000, 0, 0.10)
        assert math.isnan(result)

    def test_negative_fcf_returns_nan(self):
        result = implied_growth(1000, -50, 0.10)
        assert math.isnan(result)

    def test_high_growth_implied(self):
        """A very expensive stock implies high growth."""
        # EV = 80x FCF implies substantial growth
        result = implied_growth(8000, 100, 0.10)
        assert result > 0.10  # Must imply >10% growth


class TestReverseDCFGap:
    def test_positive_gap(self):
        """Delivered > implied = positive gap (good)."""
        gap = reverse_dcf_gap(1000, 100, 0.15, 0.10)
        # implied_growth at EV=1000 FCF=100 WACC=10% should be moderate
        assert gap is not None
        assert gap > 0  # 15% delivered should exceed implied for 10x EV/FCF

    def test_non_convergence_returns_none(self):
        gap = reverse_dcf_gap(-100, 50, 0.10, 0.10)
        assert gap is None


class TestComponentScores:
    def test_ev_ebit_low_is_good(self):
        """Low EV/EBIT scores high (inverted)."""
        assert ev_ebit_score(8.0) > ev_ebit_score(25.0)
        assert ev_ebit_score(8.0) > 8.0

    def test_ev_ebit_extreme(self):
        assert ev_ebit_score(5.0) == 10.0
        assert ev_ebit_score(40.0) == 0.0

    def test_fcf_yield_high_is_good(self):
        assert fcf_yield_score(0.12) == 10.0
        assert fcf_yield_score(0.0) == 0.0
        assert fcf_yield_score(0.05) == pytest.approx(5.0)

    def test_shareholder_yield(self):
        assert shareholder_yield_score(0.02, 0.03, 0.03) == 5.0
        assert shareholder_yield_score(0.0, 0.0, 0.0) == 0.0


class TestValuationScore:
    def test_excluded_negative_ebit(self):
        """EBIT <= 0 => excluded."""
        score, breakdown = valuation_score(
            ev=5000, ebit=-100, fcf=200, fcf_5y_cagr=0.08,
            market_cap=4000, dividend_yield=0.02, buyback_yield=0.03,
            debt_paydown_yield=0.01, risk_free_rate=0.04,
            fcf_5y_median=200,
        )
        assert score is None
        assert "ebit_negative" in breakdown["excluded"]

    def test_excluded_ev_ebit_too_high(self):
        """EV/EBIT > 45 => excluded."""
        score, breakdown = valuation_score(
            ev=50000, ebit=1000, fcf=800, fcf_5y_cagr=0.08,
            market_cap=48000, dividend_yield=0.01, buyback_yield=0.01,
            debt_paydown_yield=0.0, risk_free_rate=0.04,
            fcf_5y_median=700,
        )
        assert score is None
        assert "ev_ebit" in breakdown["excluded"]

    def test_excluded_negative_fcf_median(self):
        """5y median FCF <= 0 => excluded."""
        score, breakdown = valuation_score(
            ev=5000, ebit=500, fcf=200, fcf_5y_cagr=0.05,
            market_cap=4500, dividend_yield=0.02, buyback_yield=0.0,
            debt_paydown_yield=0.0, risk_free_rate=0.04,
            fcf_5y_median=-100,
        )
        assert score is None
        assert "fcf_5y_median" in breakdown["excluded"]

    def test_excluded_implied_growth_too_high(self):
        """Implied growth > 25% => excluded."""
        # EV/FCF=80x at WACC=10% implies ~26.7% growth, EV/EBIT=40 passes cap
        score, breakdown = valuation_score(
            ev=8000, ebit=200, fcf=100, fcf_5y_cagr=0.05,
            market_cap=7500, dividend_yield=0.0, buyback_yield=0.0,
            debt_paydown_yield=0.0, risk_free_rate=0.05,
            fcf_5y_median=100,
        )
        assert score is None
        assert "implied_growth" in breakdown["excluded"]

    def test_valid_score_in_range(self):
        """A reasonable company scores between 0 and 35."""
        score, breakdown = valuation_score(
            ev=10000, ebit=1000, fcf=800, fcf_5y_cagr=0.08,
            market_cap=9000, dividend_yield=0.02, buyback_yield=0.03,
            debt_paydown_yield=0.01, risk_free_rate=0.04,
            fcf_5y_median=700,
        )
        assert score is not None
        assert 0 <= score <= 35
        assert "ev_ebit_points" in breakdown
        assert "fcf_yield_points" in breakdown
        assert "reverse_dcf_points" in breakdown

    def test_wacc_floor(self):
        """WACC is floored at 8% even if risk_free + ERP is lower."""
        _, breakdown = valuation_score(
            ev=10000, ebit=1000, fcf=800, fcf_5y_cagr=0.08,
            market_cap=9000, dividend_yield=0.02, buyback_yield=0.02,
            debt_paydown_yield=0.0, risk_free_rate=0.01,
            fcf_5y_median=700,
        )
        assert breakdown["wacc"] >= 0.08
