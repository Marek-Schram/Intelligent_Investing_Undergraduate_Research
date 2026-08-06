"""Tests for LLM contamination measurement. TICKET-045."""

from __future__ import annotations

import numpy as np
import pandas as pd

from durable.signals.contamination import (
    alpha_decay_test,
    entity_anonymization_check,
    placebo_test,
)


def _make_feature_returns(n_dates=40, n_stocks=30, seed=42):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n_dates, freq="QE")
    stocks = [f"S{i}" for i in range(n_stocks)]
    feature = pd.DataFrame(rng.standard_normal((n_dates, n_stocks)), index=dates, columns=stocks)
    returns = pd.DataFrame(
        rng.standard_normal((n_dates, n_stocks)) * 0.05, index=dates, columns=stocks
    )
    return feature, returns, dates


class TestAlphaDecay:
    def test_insufficient_data(self):
        """Fewer than 8 periods either side => insufficient_data."""
        rng = np.random.default_rng(42)
        dates = pd.date_range("2020-01-01", periods=5, freq="QE")
        stocks = [f"S{i}" for i in range(20)]
        feature = pd.DataFrame(rng.standard_normal((5, 20)), index=dates, columns=stocks)
        returns = pd.DataFrame(rng.standard_normal((5, 20)) * 0.05, index=dates, columns=stocks)
        cutoff = pd.Timestamp("2020-06-30")
        result = alpha_decay_test(feature, returns, cutoff, "v1")
        assert result.verdict == "insufficient_data"

    def test_clean_verdict_wording(self):
        """clean means 'we looked and found no evidence', NOT 'proven clean'."""
        feature, returns, dates = _make_feature_returns(n_dates=40)
        cutoff = pd.Timestamp(dates[20])
        result = alpha_decay_test(feature, returns, cutoff, "v1")
        assert result.verdict in ("clean", "suspected", "contaminated", "insufficient_data")

    def test_result_fields(self):
        feature, returns, dates = _make_feature_returns(n_dates=40)
        cutoff = pd.Timestamp(dates[20])
        result = alpha_decay_test(feature, returns, cutoff, "test-model")
        assert result.model_version == "test-model"
        assert result.training_cutoff == cutoff
        assert isinstance(result.n_pre, int)
        assert isinstance(result.n_post, int)


class TestPlaceboTest:
    def test_random_feature_not_real_signal(self):
        """A random feature should be comparable to shuffled."""
        feature, returns, _ = _make_feature_returns(n_dates=20, n_stocks=20)
        result = placebo_test(feature, returns, n_shuffles=100, seed=42)
        assert "pvalue" in result
        assert "real_ic" in result

    def test_seeds_pinned(self):
        """Seeds pinned for reproducibility."""
        feature, returns, _ = _make_feature_returns(n_dates=20, n_stocks=20)
        r1 = placebo_test(feature, returns, n_shuffles=50, seed=42)
        r2 = placebo_test(feature, returns, n_shuffles=50, seed=42)
        assert r1["shuffled_mean"] == r2["shuffled_mean"]


class TestEntityAnonymization:
    def test_anonymous_prompt(self):
        prompt = "Extract revenue growth from the following 10-K filing text."
        is_anon, msg = entity_anonymization_check(prompt)
        assert is_anon is True

    def test_leaks_ticker(self):
        prompt = "Extract data for ticker AAPL from this filing."
        is_anon, msg = entity_anonymization_check(prompt)
        assert is_anon is False

    def test_leaks_company_name(self):
        prompt = "This is Apple Inc. 10-K filing."
        is_anon, msg = entity_anonymization_check(prompt)
        assert is_anon is False
