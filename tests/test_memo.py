"""Tests for quarterly memo. TICKET-017, TICKET-046."""

from __future__ import annotations

from datetime import date

import pytest

from durable.reporting.memo import (
    BearCase,
    MemoContent,
    MissingBearCaseError,
    PromotionalLanguageError,
    SellEntry,
    bear_case_to_disconfirming_evidence,
    generate_memo,
    validate_bear_case,
    validate_memo,
    validate_narrative,
)


def _valid_bear_case(ticker: str) -> BearCase:
    return BearCase(
        ticker=ticker,
        bear_text=f"Bear case for {ticker}: revenue concentration risk",
        falsifiers=[
            "Revenue from top customer drops below 30%",
            "New customer contributes >10% within 2 quarters",
            "Gross margin expands 200bps YoY",
        ],
        citations=["10-K FY2023 p.12", "10-Q Q1 2024 risk factors"],
    )


class TestGenerateMemo:
    def test_leads_with_sleeve_vs_vti(self):
        """Memo leads with Sleeve C+E vs VTI — acceptance criterion."""
        memo, _ = generate_memo(
            as_of=date(2024, 8, 16),
            sleeve_c_return=0.08,
            sleeve_e_return=0.12,
            vti_return=0.10,
            total_return=0.09,
            benchmark_return=0.10,
            sells=[],
            buys=["AAPL"],
            bear_cases=[_valid_bear_case("AAPL")],
            n_positions=20,
            cash_pct=0.02,
            period="Q3 2024",
        )
        assert memo.sleeve_c_return == 0.08
        assert memo.sleeve_e_return == 0.12
        assert memo.vti_return == 0.10

    def test_every_sell_names_rule(self):
        """Every sell names its S1-S5 rule — acceptance criterion."""
        memo, _ = generate_memo(
            as_of=date(2024, 8, 16),
            sleeve_c_return=0.08,
            sleeve_e_return=0.12,
            vti_return=0.10,
            total_return=0.09,
            benchmark_return=0.10,
            sells=[
                SellEntry(ticker="WEAK", sell_rule="S1: rank out of top 80 at two consecutive", rationale="Deteriorating quality"),
                SellEntry(ticker="FRAUD", sell_rule="S2: exclusion-level flag", rationale="Accounting irregularity"),
            ],
            buys=[],
            bear_cases=[],
            n_positions=18,
            cash_pct=0.05,
            period="Q3 2024",
        )
        for sell in memo.sells:
            assert sell.sell_rule.startswith("S")

    def test_sell_without_rule_fails_validation(self):
        """Sell without S1-S5 rule fails validation."""
        memo = MemoContent(
            as_of=date(2024, 8, 16),
            sleeve_c_return=0.08,
            sleeve_e_return=0.12,
            vti_return=0.10,
            period="Q3 2024",
            total_return=0.09,
            benchmark_return=0.10,
            sells=[SellEntry(ticker="BAD", sell_rule="", rationale="No rule cited")],
            buys=[],
            bear_cases=[],
            n_positions=19,
            cash_pct=0.03,
        )
        issues = validate_memo(memo)
        assert any("does not name its rule" in i for i in issues)

    def test_includes_bear_case(self):
        """Bear case included for buys — acceptance criterion."""
        memo, _ = generate_memo(
            as_of=date(2024, 8, 16),
            sleeve_c_return=0.08,
            sleeve_e_return=0.12,
            vti_return=0.10,
            total_return=0.09,
            benchmark_return=0.10,
            sells=[],
            buys=["NEWCO"],
            bear_cases=[_valid_bear_case("NEWCO")],
            n_positions=21,
            cash_pct=0.01,
            period="Q3 2024",
        )
        assert len(memo.bear_cases) == 1
        assert memo.bear_cases[0].ticker == "NEWCO"
        assert len(memo.bear_cases[0].falsifiers) == 3

    def test_missing_bear_case_raises_sleeve_e(self):
        """Sleeve E buy without bear case raises MissingBearCaseError."""
        with pytest.raises(MissingBearCaseError):
            generate_memo(
                as_of=date(2024, 8, 16),
                sleeve_c_return=0.08,
                sleeve_e_return=0.12,
                vti_return=0.10,
                total_return=0.09,
                benchmark_return=0.10,
                sells=[],
                buys=["NOCASE"],
                bear_cases=[],  # No bear case provided
                n_positions=21,
                cash_pct=0.01,
                period="Q3 2024",
                sleeve_e_buys=["NOCASE"],
            )

    def test_blank_mistake_line(self):
        """Memo has blank 'mistake' line — acceptance criterion."""
        memo, _ = generate_memo(
            as_of=date(2024, 8, 16),
            sleeve_c_return=0.08,
            sleeve_e_return=0.12,
            vti_return=0.10,
            total_return=0.09,
            benchmark_return=0.10,
            sells=[],
            buys=[],
            bear_cases=[],
            n_positions=20,
            cash_pct=0.02,
            period="Q3 2024",
        )
        assert memo.mistakes == ""
        assert hasattr(memo, "mistakes")

    def test_48h_time_stated(self):
        """48h review deadline stated — acceptance criterion."""
        memo, _ = generate_memo(
            as_of=date(2024, 8, 16),
            sleeve_c_return=0.08,
            sleeve_e_return=0.12,
            vti_return=0.10,
            total_return=0.09,
            benchmark_return=0.10,
            sells=[],
            buys=[],
            bear_cases=[],
            n_positions=20,
            cash_pct=0.02,
            period="Q3 2024",
        )
        assert memo.review_deadline_hours == 48

    def test_bear_case_needs_three_falsifiers(self):
        """Bear case with != 3 falsifiers raises."""
        bad_bear = BearCase(
            ticker="BAD",
            bear_text="Some bear case",
            falsifiers=["Only one"],
            citations=["10-K"],
        )
        with pytest.raises(MissingBearCaseError, match="3 falsifiers"):
            generate_memo(
                as_of=date(2024, 8, 16),
                sleeve_c_return=0.08,
                sleeve_e_return=0.12,
                vti_return=0.10,
                total_return=0.09,
                benchmark_return=0.10,
                sells=[],
                buys=["BAD"],
                bear_cases=[bad_bear],
                n_positions=21,
                cash_pct=0.01,
                period="Q3 2024",
            )


class TestBearCaseT046:
    """T-046 bear case requirements."""

    def test_sleeve_e_buy_requires_bear_case(self):
        """Sleeve E buy without bear case raises — REQUIRED."""
        with pytest.raises(MissingBearCaseError, match="Sleeve E"):
            generate_memo(
                as_of=date(2024, 8, 16),
                sleeve_c_return=0.08,
                sleeve_e_return=0.12,
                vti_return=0.10,
                total_return=0.09,
                benchmark_return=0.10,
                sells=[],
                buys=["SMOL"],
                bear_cases=[],
                n_positions=21,
                cash_pct=0.01,
                period="Q3 2024",
                sleeve_e_buys=["SMOL"],
            )

    def test_sleeve_c_buy_without_bear_case_warns(self):
        """Sleeve C buy without bear case is warned, not raised."""
        _, warnings = generate_memo(
            as_of=date(2024, 8, 16),
            sleeve_c_return=0.08,
            sleeve_e_return=0.12,
            vti_return=0.10,
            total_return=0.09,
            benchmark_return=0.10,
            sells=[],
            buys=["BIGCO"],
            bear_cases=[],
            n_positions=21,
            cash_pct=0.01,
            period="Q3 2024",
            sleeve_e_buys=[],
        )
        assert any("warned" in w for w in warnings)

    def test_promotional_language_raises(self):
        """Bear text with promotional language raises."""
        promo_bear = BearCase(
            ticker="HYPE",
            bear_text="This is the next Amazon and a guaranteed multi-bagger",
            falsifiers=["Revenue drops", "Margin compression", "Customer churn"],
            citations=["10-K FY2023"],
        )
        with pytest.raises(PromotionalLanguageError):
            generate_memo(
                as_of=date(2024, 8, 16),
                sleeve_c_return=0.08,
                sleeve_e_return=0.12,
                vti_return=0.10,
                total_return=0.09,
                benchmark_return=0.10,
                sells=[],
                buys=["HYPE"],
                bear_cases=[promo_bear],
                n_positions=21,
                cash_pct=0.01,
                period="Q3 2024",
            )

    def test_validate_narrative_clean(self):
        is_valid, _ = validate_narrative("Revenue concentration risk from single customer")
        assert is_valid is True

    def test_validate_narrative_promotional(self):
        is_valid, _ = validate_narrative("this is a moonshot opportunity")
        assert is_valid is False

    def test_uncited_bear_case_flagged(self):
        """Uncited bear case raises issue in validation."""
        bc = BearCase(
            ticker="NOCITE",
            bear_text="Revenue risk from concentration",
            falsifiers=["Rev drops", "Margin falls", "Churn rises"],
            citations=[],
            sleeve="E",
        )
        issues = validate_bear_case(bc)
        assert any("no filing citations" in i for i in issues)

    def test_no_bear_case_requires_checked_sources(self):
        """'No bear case could be constructed' needs checked_sources."""
        bc = BearCase(
            ticker="CLEAN",
            bear_text="No bear case could be constructed after review",
            falsifiers=["Hypothetical: rev drops", "Hypothetical: margin", "Hypothetical: churn"],
            citations=["10-K FY2023"],
        )
        issues = validate_bear_case(bc)
        assert any("checked_sources" in i for i in issues)

    def test_no_bear_case_valid_with_all_sources(self):
        """'No bear case' is valid when all required sources are checked."""
        bc = BearCase(
            ticker="CLEAN",
            bear_text="No bear case could be constructed after review",
            falsifiers=["Hypothetical: rev drops", "Hypothetical: margin", "Hypothetical: churn"],
            citations=["10-K FY2023"],
            checked_sources=["filings", "short_interest", "credit", "insider_activity"],
        )
        issues = validate_bear_case(bc)
        assert not any("checked_sources" in i for i in issues)

    def test_bear_case_to_disconfirming_evidence(self):
        """Bear case copied verbatim into decisions.csv."""
        bc = _valid_bear_case("TEST")
        evidence = bear_case_to_disconfirming_evidence(bc)
        assert evidence == bc.bear_text
