"""Tests for neglect score. TICKET-026."""

from __future__ import annotations

from datetime import date

import pytest

from durable.discovery.neglect import (
    MAX_NEGLECT_SCORE,
    NeglectInputs,
    NeglectResult,
    compute_neglect_score,
    _score_analyst_count,
    _score_institutional_ownership,
    _score_media_mentions,
    _score_initiation,
)


class TestAnalystScoring:
    def test_zero_analysts_max_score(self):
        assert _score_analyst_count(0) == 8

    def test_one_analyst(self):
        assert _score_analyst_count(1) == 6

    def test_two_analysts(self):
        assert _score_analyst_count(2) == 4

    def test_three_analysts(self):
        assert _score_analyst_count(3) == 2

    def test_four_or_more_zero(self):
        assert _score_analyst_count(4) == 0
        assert _score_analyst_count(10) == 0

    def test_none_returns_zero(self):
        assert _score_analyst_count(None) == 0


class TestInstitutionalScoring:
    def test_below_10_pct(self):
        assert _score_institutional_ownership(0.05) == 7

    def test_between_10_20(self):
        assert _score_institutional_ownership(0.15) == 5

    def test_between_20_30(self):
        assert _score_institutional_ownership(0.25) == 3

    def test_between_30_40(self):
        assert _score_institutional_ownership(0.35) == 1

    def test_at_or_above_40(self):
        assert _score_institutional_ownership(0.40) == 0
        assert _score_institutional_ownership(0.80) == 0

    def test_none_returns_zero(self):
        assert _score_institutional_ownership(None) == 0


class TestMediaScoring:
    def test_bottom_decile(self):
        assert _score_media_mentions(1) == 5

    def test_second_decile(self):
        assert _score_media_mentions(2) == 3

    def test_third_decile(self):
        assert _score_media_mentions(3) == 1

    def test_higher_deciles_zero(self):
        assert _score_media_mentions(4) == 0
        assert _score_media_mentions(10) == 0

    def test_none_returns_zero(self):
        assert _score_media_mentions(None) == 0


class TestInitiationScoring:
    def test_no_initiation_scores_5(self):
        assert _score_initiation(False) == 5

    def test_has_initiation_scores_0(self):
        assert _score_initiation(True) == 0

    def test_none_returns_zero(self):
        assert _score_initiation(None) == 0


class TestComputeNeglectScore:
    def test_caps_at_25(self):
        """Score caps at 25 — acceptance criterion."""
        result = compute_neglect_score(
            "TINY",
            analyst_count=0,  # 8
            institutional_ownership_pct=0.05,  # 7
            media_mentions_decile=1,  # 5
            has_sell_side_initiation_24m=False,  # 5
        )
        # Raw = 25, cap = 25
        assert result.score == 25
        assert result.capped_score == 25

    def test_raw_inputs_returned(self):
        """Raw inputs returned — acceptance criterion."""
        result = compute_neglect_score(
            "TEST",
            analyst_count=2,
            institutional_ownership_pct=0.15,
            media_mentions_decile=3,
            has_sell_side_initiation_24m=True,
        )
        assert result.inputs.analyst_count == 2
        assert result.inputs.institutional_ownership_pct == 0.15
        assert result.inputs.media_mentions_decile == 3
        assert result.inputs.has_sell_side_initiation_24m is True

    def test_component_breakdown(self):
        result = compute_neglect_score(
            "COMP",
            analyst_count=1,  # 6
            institutional_ownership_pct=0.25,  # 3
            media_mentions_decile=2,  # 3
            has_sell_side_initiation_24m=False,  # 5
        )
        assert result.analyst_sub == 6
        assert result.institutional_sub == 3
        assert result.media_sub == 3
        assert result.initiation_sub == 5
        assert result.score == 17
        assert result.capped_score == 17

    def test_all_none_returns_zero(self):
        result = compute_neglect_score("EMPTY")
        assert result.score == 0
        assert result.capped_score == 0

    def test_13f_filed_at_stored(self):
        """13F available_at = filed_at — acceptance criterion."""
        filed = date(2025, 5, 15)
        result = compute_neglect_score(
            "INST",
            institutional_ownership_pct=0.08,
            filed_at=filed,
        )
        assert result.inputs.filed_at == filed

    def test_module_comment_states_premium_contested(self):
        """Module comment states the premium is contested — acceptance criterion."""
        import durable.discovery.neglect as mod
        assert "contested" in mod.__doc__.lower()
