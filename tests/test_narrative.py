"""Tests for narrative validation module. TICKET-021.

Acceptance criteria:
- Rejects banned phrases
- 'outperformed' without a CI is rejected
- No negative contributor is rejected
- Unqualified 'alpha' is rejected
- Passes for 20 randomized inputs including bad-loss cases
- The writer RAISES rather than writing a failing narrative
"""

from __future__ import annotations

import random

import pytest

from durable.reporting.narrative import (
    BANNED_PHRASES,
    NarrativeValidationError,
    _check_banned_phrases,
    _check_negative_contributor,
    _check_outperformed_without_ci,
    _check_unqualified_alpha,
    generate_narrative,
    validate_narrative,
)

# ---------------------------------------------------------------------------
# Test banned phrase rejection
# ---------------------------------------------------------------------------


class TestBannedPhrases:
    """Test that all banned phrases are detected."""

    @pytest.mark.parametrize("phrase", BANNED_PHRASES)
    def test_each_banned_phrase_rejected(self, phrase: str):
        """Every banned phrase in the list triggers a violation."""
        text = f"The portfolio returned +5.2% vs benchmark +4.1%. {phrase}. AAPL detracted 1.2%."
        violations = _check_banned_phrases(text)
        assert len(violations) >= 1
        assert any(phrase in v.lower() for v in violations)

    def test_banned_phrase_case_insensitive(self):
        """Banned phrases are caught regardless of case."""
        text = "We BELIEVE strongly. AAPL lost 3%."
        violations = _check_banned_phrases(text)
        assert len(violations) >= 1

    def test_no_banned_phrases_passes(self):
        """Clean text with no banned phrases passes."""
        text = (
            "The portfolio returned +5.2% vs benchmark +4.1%. "
            "Sector allocation in Technology drove the excess. "
            "AAPL detracted 1.5% from returns."
        )
        violations = _check_banned_phrases(text)
        assert violations == []


# ---------------------------------------------------------------------------
# Test outperformed without CI
# ---------------------------------------------------------------------------


class TestOutperformedWithoutCI:
    """'outperformed' requires confidence interval context."""

    def test_outperformed_without_ci_rejected(self):
        """Bare 'outperformed' without any CI context is rejected."""
        text = "The portfolio outperformed the benchmark this quarter. MSFT detracted 2%."
        violations = _check_outperformed_without_ci(text)
        assert len(violations) == 1
        assert "outperformed" in violations[0].lower()

    def test_outperformed_with_bracket_ci_passes(self):
        """'outperformed' with [X%, Y%] CI passes."""
        text = "The portfolio outperformed the benchmark by 1.2% [0.3%, 2.1%]. MSFT detracted 2%."
        violations = _check_outperformed_without_ci(text)
        assert violations == []

    def test_outperformed_with_paren_ci_passes(self):
        """'outperformed' with (X% to Y%) CI passes."""
        text = "The portfolio outperformed (0.5% to 2.3%). AAPL detracted 1%."
        violations = _check_outperformed_without_ci(text)
        assert violations == []

    def test_outperformed_with_ci_label_passes(self):
        """'outperformed' with '95% CI' label passes."""
        text = "The portfolio outperformed the benchmark, 95% CI [0.1%, 1.9%]. TSLA detracted 3%."
        violations = _check_outperformed_without_ci(text)
        assert violations == []

    def test_outperformed_with_plus_minus_passes(self):
        """'outperformed' with ± passes."""
        text = "The portfolio outperformed the benchmark by 1.5% ± 0.8%. XOM detracted 1%."
        violations = _check_outperformed_without_ci(text)
        assert violations == []

    def test_outperformed_far_from_ci_rejected(self):
        """CI context too far from 'outperformed' is rejected."""
        # CI is more than 200 chars away
        filler = "x " * 120
        text = f"The portfolio outperformed. {filler} [0.1%, 1.9%]. AAPL detracted 2%."
        violations = _check_outperformed_without_ci(text)
        assert len(violations) == 1


# ---------------------------------------------------------------------------
# Test unqualified alpha
# ---------------------------------------------------------------------------


class TestUnqualifiedAlpha:
    """'alpha' must be qualified with statistical context."""

    def test_unqualified_alpha_rejected(self):
        """Bare 'alpha' without statistical context is rejected."""
        text = "The portfolio generated alpha this quarter. AAPL detracted 1%."
        violations = _check_unqualified_alpha(text)
        assert len(violations) == 1
        assert "alpha" in violations[0].lower()

    def test_alpha_with_tstat_passes(self):
        """'alpha' with t-stat passes."""
        text = "Factor-model alpha of +1.2% (t-stat = 1.85, |t| < 2). MSFT detracted 2%."
        violations = _check_unqualified_alpha(text)
        assert violations == []

    def test_alpha_with_pvalue_passes(self):
        """'alpha' with p-value passes."""
        text = "The alpha estimate is 0.8% (p < 0.05). AAPL detracted 1%."
        violations = _check_unqualified_alpha(text)
        assert violations == []

    def test_alpha_with_insignificant_passes(self):
        """'alpha' described as insignificant passes."""
        text = "The alpha is statistically insignificant at this sample size. TSLA detracted 3%."
        violations = _check_unqualified_alpha(text)
        assert violations == []

    def test_alpha_with_ci_passes(self):
        """'alpha' with CI passes."""
        text = "Annualized alpha of 1.5% [-0.2%, 3.2%] 95% CI. XOM detracted 0.5%."
        violations = _check_unqualified_alpha(text)
        assert violations == []

    def test_alphabetical_not_flagged(self):
        """Words containing 'alpha' as a substring should not trigger."""
        text = "We sorted results alphabetically. AAPL detracted 2%."
        violations = _check_unqualified_alpha(text)
        assert violations == []


# ---------------------------------------------------------------------------
# Test negative contributor requirement
# ---------------------------------------------------------------------------


class TestNegativeContributor:
    """Narrative must name at least one negative contributor."""

    def test_no_negative_contributor_rejected(self):
        """Narrative with only positive commentary is rejected."""
        text = (
            "The portfolio returned +5.2% vs benchmark +4.1%. "
            "AAPL contributed +1.2%. MSFT contributed +0.8%."
        )
        violations = _check_negative_contributor(text)
        assert len(violations) == 1
        msg = violations[0].lower()
        assert "negative contributor" in msg or "worst contributor" in msg

    def test_detracted_passes(self):
        """'detracted' satisfies the negative contributor requirement."""
        text = "AAPL contributed +1.2%. XOM detracted 0.5% from returns."
        violations = _check_negative_contributor(text)
        assert violations == []

    def test_worst_contributor_passes(self):
        """'worst contributor' satisfies the requirement."""
        text = "Best contributor AAPL +1.2%. Worst contributor XOM -0.5%."
        violations = _check_negative_contributor(text)
        assert violations == []

    def test_declined_with_number_passes(self):
        """'declined X%' satisfies the requirement."""
        text = "AAPL gained 5%. TSLA declined 3.2% over the period."
        violations = _check_negative_contributor(text)
        assert violations == []


# ---------------------------------------------------------------------------
# Test validate_narrative (integration)
# ---------------------------------------------------------------------------


class TestValidateNarrative:
    """Integration tests for validate_narrative."""

    def test_empty_narrative_rejected(self):
        """Empty string is rejected."""
        assert validate_narrative("") != []
        assert validate_narrative("   ") != []

    def test_valid_narrative_passes(self):
        """A well-formed narrative with all required elements passes."""
        text = (
            "The portfolio returned +5.20% vs the benchmark's +4.10%, "
            "1.10% above [+0.30%, +1.90%] 95% CI. "
            "The primary Brinson driver was Technology (selection effect +0.80%). "
            "Since inception, annualized excess is +2.10% [+0.50%, +3.70%] — "
            "statistically significant. "
            "Factor-model alpha of +1.50% (t-stat = 2.10, |t| > 2). "
            "PBO is 0.35. No process violations this period. "
            "Best contributor: AAPL (+1.20%). "
            "Worst contributor XOM detracted 0.50% from returns."
        )
        violations = validate_narrative(text)
        assert violations == []

    def test_multiple_violations_all_reported(self):
        """Multiple violations are all captured."""
        text = "We believe this is a compelling opportunity and we have strong conviction."
        violations = validate_narrative(text)
        # Should catch: 'we believe', 'compelling opportunity', 'strong conviction',
        # no negative contributor
        assert len(violations) >= 3


# ---------------------------------------------------------------------------
# Test generate_narrative raises on failure
# ---------------------------------------------------------------------------


class TestGenerateNarrativeRaises:
    """The writer raises NarrativeValidationError rather than producing bad output."""

    def _make_valid_inputs(self) -> tuple[dict, dict, dict, dict]:
        """Create a set of valid inputs for generate_narrative."""
        metrics = {
            "total_return": 0.052,
            "benchmark_return": 0.041,
            "excess_return": 0.011,
            "ci_low": 0.003,
            "ci_high": 0.019,
            "inception_excess": 0.021,
            "inception_ci_low": 0.005,
            "inception_ci_high": 0.037,
            "factor_alpha": 0.015,
            "factor_tstat": 2.1,
            "pbo": 0.35,
            "n_periods": 12,
        }
        attribution = {
            "top_sector": "Technology",
            "top_sector_effect": 0.008,
        }
        contributions = {
            "best_ticker": "AAPL",
            "best_contrib": 0.012,
            "worst_ticker": "XOM",
            "worst_contrib": -0.005,
        }
        context = {
            "process_health": "No process violations this period.",
        }
        return metrics, attribution, contributions, context

    def test_valid_inputs_produce_valid_narrative(self):
        """Valid inputs produce a narrative without raising."""
        metrics, attribution, contributions, context = self._make_valid_inputs()
        result = generate_narrative(metrics, attribution, contributions, context)
        assert isinstance(result, str)
        assert len(result) > 100

    def test_writer_raises_on_banned_phrase_in_context(self):
        """Writer raises if process_health contains a banned phrase."""
        metrics, attribution, contributions, context = self._make_valid_inputs()
        context["process_health"] = "We believe the process is working well."
        with pytest.raises(NarrativeValidationError):
            generate_narrative(metrics, attribution, contributions, context)

    def test_writer_raises_not_writes_failing_narrative(self):
        """The contract: raise, never return a failing narrative."""
        metrics, attribution, contributions, context = self._make_valid_inputs()
        # Inject a banned phrase via process_health
        context["process_health"] = "The portfolio is positioned to benefit from tailwinds."
        with pytest.raises(NarrativeValidationError) as exc_info:
            generate_narrative(metrics, attribution, contributions, context)
        assert "positioned to benefit" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# Test with 20 randomized inputs including bad-loss cases
# ---------------------------------------------------------------------------


class TestRandomizedInputs:
    """20 randomized inputs including bad-loss cases must pass or raise correctly."""

    def _random_metrics(self, rng: random.Random, bad_loss: bool = False) -> dict:
        """Generate random metrics. bad_loss makes returns very negative."""
        if bad_loss:
            total = rng.uniform(-0.30, -0.05)
            bench = rng.uniform(-0.05, 0.05)
        else:
            total = rng.uniform(-0.10, 0.15)
            bench = rng.uniform(-0.05, 0.10)

        excess = total - bench
        ci_half = rng.uniform(0.005, 0.02)
        inc_excess = rng.uniform(-0.05, 0.05)
        inc_ci_half = rng.uniform(0.01, 0.03)

        return {
            "total_return": total,
            "benchmark_return": bench,
            "excess_return": excess,
            "ci_low": excess - ci_half,
            "ci_high": excess + ci_half,
            "inception_excess": inc_excess,
            "inception_ci_low": inc_excess - inc_ci_half,
            "inception_ci_high": inc_excess + inc_ci_half,
            "factor_alpha": rng.uniform(-0.02, 0.03),
            "factor_tstat": rng.uniform(-1.5, 2.5),
            "pbo": rng.uniform(0.1, 0.6),
            "n_periods": rng.randint(8, 40),
        }

    def _random_attribution(self, rng: random.Random) -> dict:
        sectors = ["Technology", "Healthcare", "Financials", "Energy", "Consumer"]
        return {
            "top_sector": rng.choice(sectors),
            "top_sector_effect": rng.uniform(-0.01, 0.02),
        }

    def _random_contributions(self, rng: random.Random, bad_loss: bool = False) -> dict:
        tickers = ["AAPL", "MSFT", "GOOG", "AMZN", "XOM", "JPM", "TSLA", "JNJ", "PG", "V"]
        best = rng.choice(tickers)
        worst = rng.choice([t for t in tickers if t != best])
        worst_contrib = rng.uniform(-0.10, -0.03) if bad_loss else rng.uniform(-0.03, -0.001)
        return {
            "best_ticker": best,
            "best_contrib": rng.uniform(0.005, 0.03),
            "worst_ticker": worst,
            "worst_contrib": worst_contrib,
        }

    @pytest.mark.parametrize("seed", range(20))
    def test_randomized_valid_input_passes(self, seed: int):
        """20 randomized inputs (including bad-loss) produce valid narratives.

        Seeds 0-4 are bad-loss cases (large negative returns).
        """
        rng = random.Random(seed)
        bad_loss = seed < 5  # First 5 are bad-loss cases

        metrics = self._random_metrics(rng, bad_loss=bad_loss)
        attribution = self._random_attribution(rng)
        contributions = self._random_contributions(rng, bad_loss=bad_loss)
        context = {"process_health": "No process violations this period."}

        # Should produce a valid narrative (not raise)
        result = generate_narrative(metrics, attribution, contributions, context)
        assert isinstance(result, str)
        assert len(result) > 50

        # Double-check: validate_narrative confirms it passes
        violations = validate_narrative(result)
        assert violations == [], f"Seed {seed} produced violations: {violations}"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_outperformed_in_different_forms(self):
        """Various forms of 'outperformed' are all caught."""
        for word in ["outperformed", "Outperformed", "OUTPERFORMED"]:
            text = f"The strategy {word} the market. AAPL detracted 1%."
            violations = _check_outperformed_without_ci(text)
            assert len(violations) >= 1, f"Failed to catch: {word}"

    def test_alpha_in_compound_words_not_flagged(self):
        """'alpha' inside compound words is not flagged."""
        # 'alphabetical' contains 'alpha' but word boundary check should exclude it
        text = "Results were sorted alphabetically by ticker. AAPL detracted 1%."
        violations = _check_unqualified_alpha(text)
        assert violations == []

    def test_multiple_outperformed_one_ci(self):
        """Multiple 'outperformed' — only one needs CI context."""
        text = "The portfolio outperformed [0.3%, 1.9%] 95% CI. AAPL detracted 2%."
        violations = _check_outperformed_without_ci(text)
        assert violations == []

    def test_narrative_validation_error_is_value_error(self):
        """NarrativeValidationError is a ValueError subclass."""
        assert issubclass(NarrativeValidationError, ValueError)

    def test_validate_returns_list(self):
        """validate_narrative always returns a list."""
        result = validate_narrative("some text. AAPL detracted 2%.")
        assert isinstance(result, list)
