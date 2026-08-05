"""Tests for discovery screens. TICKET-027."""

from __future__ import annotations

import pytest

from durable.discovery.screens import (
    ALL_SCREENS,
    BORING_SIC_GROUPS,
    CIK_PAD_WIDTH,
    FILING_LANGUAGE_KEYWORDS,
    MAX_REQUESTS_PER_SECOND,
    ScreenHit,
    ScreenResult,
    ScreenType,
    pad_cik,
    run_all_screens,
    screen_boring_industry,
    screen_coverage_gap,
    screen_filing_language,
    screen_insider_cluster,
    screen_institutional_conviction,
    screen_quiet_compounder,
    screen_spinoff,
    validate_user_agent,
)

VALID_UA = "John Doe john@example.com"


class TestAllSevenScreens:
    """All seven screens implemented — acceptance criterion."""

    def test_seven_screen_types(self):
        assert len(ALL_SCREENS) == 7

    def test_all_screens_run(self):
        result = run_all_screens([], user_agent=VALID_UA)
        assert len(result.screens_run) == 7


class TestUserAgentAsserted:
    """User-Agent asserted — acceptance criterion."""

    def test_missing_user_agent_raises(self):
        with pytest.raises(ValueError, match="User-Agent"):
            run_all_screens([], user_agent=None)

    def test_empty_user_agent_raises(self):
        with pytest.raises(ValueError, match="User-Agent"):
            run_all_screens([], user_agent="")

    def test_too_short_user_agent_raises(self):
        with pytest.raises(ValueError, match="User-Agent"):
            run_all_screens([], user_agent="short")

    def test_valid_user_agent_passes(self):
        result = run_all_screens([], user_agent=VALID_UA)
        assert result is not None


class TestRateLimit:
    """<= 10 req/sec enforced — acceptance criterion."""

    def test_max_requests_constant(self):
        assert MAX_REQUESTS_PER_SECOND == 10


class TestCIKZeroPadding:
    """CIK zero-padding — acceptance criterion."""

    def test_short_cik_padded(self):
        assert pad_cik(12345) == "0000012345"

    def test_already_10_digits(self):
        assert pad_cik(1234567890) == "1234567890"

    def test_string_input(self):
        assert pad_cik("789") == "0000000789"

    def test_pad_width_is_10(self):
        assert CIK_PAD_WIDTH == 10


class TestOnlyCodeP:
    """Only code 'P' — acceptance criterion."""

    def test_code_p_counted(self):
        candidates = [{
            "ticker": "BUY",
            "analyst_count": 1,
            "form4_transactions": [
                {"insider_name": "CEO", "code": "P"},
                {"insider_name": "CFO", "code": "P"},
            ],
        }]
        hits = screen_insider_cluster(candidates)
        assert len(hits) == 1

    def test_code_a_not_counted(self):
        """Awards (code 'A') are NOT purchases."""
        candidates = [{
            "ticker": "AWARD",
            "analyst_count": 1,
            "form4_transactions": [
                {"insider_name": "CEO", "code": "A"},
                {"insider_name": "CFO", "code": "A"},
                {"insider_name": "COO", "code": "A"},
            ],
        }]
        hits = screen_insider_cluster(candidates)
        assert len(hits) == 0

    def test_mixed_codes_only_p(self):
        """Only code 'P' transactions count toward the cluster."""
        candidates = [{
            "ticker": "MIX",
            "analyst_count": 2,
            "form4_transactions": [
                {"insider_name": "CEO", "code": "P"},
                {"insider_name": "CFO", "code": "A"},
                {"insider_name": "COO", "code": "S"},
            ],
        }]
        hits = screen_insider_cluster(candidates)
        # Only 1 unique insider with code 'P', need >= 2
        assert len(hits) == 0


class TestMultiScreenHitsNoPoints:
    """Multi-screen hits add NO points — acceptance criterion."""

    def test_ticker_in_multiple_screens_counted_once(self):
        candidates = [{
            "ticker": "MULTI",
            "profitable": True,
            "market_cap": 500e6,
            "analyst_count": 1,
            "institutional_pct": 0.20,
            "sic_code": "5080",
            "durability_score": 35,
        }]
        result = run_all_screens(candidates, user_agent=VALID_UA)
        # Should appear in both coverage_gap and boring_industry
        ticker_hits = result.hits_by_ticker.get("MULTI", [])
        assert len(ticker_hits) >= 2

        # But unique_tickers only counts it once
        assert len(result.unique_tickers) == 1
        assert "MULTI" in result.unique_tickers


class TestEmptyResultValid:
    """Empty result is valid — acceptance criterion."""

    def test_no_candidates_valid(self):
        result = run_all_screens([], user_agent=VALID_UA)
        assert result.hits == []
        assert result.unique_tickers == set()

    def test_no_matches_valid(self):
        candidates = [{"ticker": "FAIL", "profitable": False, "market_cap": 100}]
        result = run_all_screens(candidates, user_agent=VALID_UA)
        assert result.hits == []


class TestCoverageGap:
    def test_qualifies(self):
        candidates = [{
            "ticker": "GAP",
            "profitable": True,
            "market_cap": 800e6,
            "analyst_count": 0,
            "institutional_pct": 0.25,
        }]
        hits = screen_coverage_gap(candidates)
        assert len(hits) == 1
        assert hits[0].ticker == "GAP"

    def test_too_many_analysts(self):
        candidates = [{
            "ticker": "COVERED",
            "profitable": True,
            "market_cap": 800e6,
            "analyst_count": 5,
            "institutional_pct": 0.25,
        }]
        hits = screen_coverage_gap(candidates)
        assert len(hits) == 0


class TestBoringIndustry:
    def test_qualifies(self):
        candidates = [{
            "ticker": "BORE",
            "sic_code": "4953",
            "durability_score": 40,
        }]
        hits = screen_boring_industry(candidates)
        assert len(hits) == 1

    def test_glamorous_sic_excluded(self):
        candidates = [{
            "ticker": "TECH",
            "sic_code": "7372",
            "durability_score": 45,
        }]
        hits = screen_boring_industry(candidates)
        assert len(hits) == 0


class TestSpinoff:
    def test_in_window(self):
        candidates = [{"ticker": "SPIN", "months_since_spinoff": 18}]
        hits = screen_spinoff(candidates)
        assert len(hits) == 1

    def test_too_recent(self):
        candidates = [{"ticker": "NEW", "months_since_spinoff": 6}]
        hits = screen_spinoff(candidates)
        assert len(hits) == 0

    def test_too_old(self):
        candidates = [{"ticker": "OLD", "months_since_spinoff": 48}]
        hits = screen_spinoff(candidates)
        assert len(hits) == 0


class TestFilingLanguage:
    def test_keyword_found(self):
        candidates = [{
            "ticker": "LANG",
            "filing_text": "The company has a long-term supply agreement with major clients.",
        }]
        hits = screen_filing_language(candidates)
        assert len(hits) == 1
        assert "long-term supply agreement" in hits[0].detail

    def test_no_keywords(self):
        candidates = [{
            "ticker": "PLAIN",
            "filing_text": "Revenue grew quarter over quarter.",
        }]
        hits = screen_filing_language(candidates)
        assert len(hits) == 0


class TestQuietCompounder:
    def test_qualifies(self):
        candidates = [{
            "ticker": "QUIET",
            "revenue_cagr_5y": 0.12,
            "fcf_cagr_5y": 0.10,
            "shares_growth_5y": -0.02,
            "roic": 0.15,
            "analyst_count": 2,
        }]
        hits = screen_quiet_compounder(candidates)
        assert len(hits) == 1

    def test_shares_growing_excluded(self):
        candidates = [{
            "ticker": "DILUTE",
            "revenue_cagr_5y": 0.12,
            "fcf_cagr_5y": 0.10,
            "shares_growth_5y": 0.05,
            "roic": 0.15,
            "analyst_count": 2,
        }]
        hits = screen_quiet_compounder(candidates)
        assert len(hits) == 0


class TestInstitutionalConviction:
    def test_qualifies(self):
        candidates = [{
            "ticker": "CONV",
            "conviction_managers": ["ManagerA", "ManagerB"],
            "analyst_count": 2,
        }]
        hits = screen_institutional_conviction(candidates)
        assert len(hits) == 1

    def test_too_few_managers(self):
        candidates = [{
            "ticker": "FEW",
            "conviction_managers": ["ManagerA"],
            "analyst_count": 2,
        }]
        hits = screen_institutional_conviction(candidates)
        assert len(hits) == 0
