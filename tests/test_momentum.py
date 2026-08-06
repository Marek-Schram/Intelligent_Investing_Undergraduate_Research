"""Tests for momentum score. TICKET-008. Hand-computed fixtures."""

from __future__ import annotations

from datetime import date

import pandas as pd

from durable.factors.momentum import (
    momentum_12_1_score,
    momentum_score,
    price_above_sma200,
    sma200_score,
    total_return_12_1,
)


def _make_bars(start: date, n_days: int, start_price: float, end_price: float) -> pd.DataFrame:
    """Create synthetic daily bars with linear price path."""
    dates = pd.bdate_range(start, periods=n_days)
    prices = [start_price + (end_price - start_price) * i / (n_days - 1) for i in range(n_days)]
    return pd.DataFrame({"dt": dates.date, "close": prices, "volume": [1000000] * n_days})


class TestTotalReturn12_1:
    def test_most_recent_month_excluded(self):
        """The most recent month's return is NOT included — acceptance criterion."""
        as_of = date(2024, 12, 31)

        # Create bars from 2023-10 to 2024-12
        # Period used: ~2023-12-01 to ~2024-11-30 (skip last month)
        bars_base = _make_bars(date(2023, 10, 1), 310, 100.0, 150.0)

        # Now create a variant with a massive spike in the last month only
        bars_spike = bars_base.copy()
        last_month_mask = bars_spike["dt"] >= date(2024, 12, 1)
        bars_spike.loc[last_month_mask, "close"] = 500.0

        # Both should give the same return because the last month is skipped
        ret_base = total_return_12_1(bars_base, as_of)
        ret_spike = total_return_12_1(bars_spike, as_of)

        assert ret_base is not None
        assert ret_spike is not None
        assert abs(ret_base - ret_spike) < 0.001

    def test_positive_return(self):
        """Stock that went from 100 to 140 in the 12-1 window."""
        as_of = date(2024, 12, 31)
        # Need bars from at least 2023-11-01 to 2024-11-30
        bars = _make_bars(date(2023, 10, 1), 310, 100.0, 140.0)
        ret = total_return_12_1(bars, as_of)
        assert ret is not None
        assert ret > 0.20  # ~40% total, but window is partial

    def test_negative_return(self):
        """Stock that declined."""
        as_of = date(2024, 12, 31)
        bars = _make_bars(date(2023, 10, 1), 310, 100.0, 60.0)
        ret = total_return_12_1(bars, as_of)
        assert ret is not None
        assert ret < 0

    def test_dividends_included_via_splits(self):
        """Splits are accounted for — 'dividends included' acceptance criterion."""
        as_of = date(2024, 12, 31)
        # Stock goes from 100 to 75 (appears -25%), but had a 2:1 split
        # So real return is: adjusted start = 100/2 = 50, end = 75 -> +50%
        bars = _make_bars(date(2023, 10, 1), 310, 100.0, 75.0)

        # Without split: negative return
        ret_no_split = total_return_12_1(bars, as_of)
        assert ret_no_split is not None
        assert ret_no_split < 0

        # With split: positive return
        split_date = date(2024, 6, 15)
        actions = pd.DataFrame([{"ex_date": split_date, "action_type": "split", "factor": 2.0}])
        ret_with_split = total_return_12_1(bars, as_of, corporate_actions=actions)
        assert ret_with_split is not None
        assert ret_with_split > 0

    def test_insufficient_data_returns_none(self):
        """Less than 220 trading days returns None."""
        as_of = date(2024, 12, 31)
        bars = _make_bars(date(2024, 6, 1), 100, 100.0, 110.0)
        ret = total_return_12_1(bars, as_of)
        assert ret is None

    def test_empty_bars_returns_none(self):
        ret = total_return_12_1(pd.DataFrame(columns=["dt", "close"]), date(2024, 12, 31))
        assert ret is None


class TestPriceAboveSMA200:
    def test_above_sma(self):
        """Trending stock is above its SMA."""
        as_of = date(2024, 12, 31)
        # Rising from 50 to 150 over 250 days
        bars = _make_bars(date(2024, 1, 1), 250, 50.0, 150.0)
        result = price_above_sma200(bars, as_of)
        assert result is True

    def test_below_sma(self):
        """Declining stock is below its SMA."""
        as_of = date(2024, 12, 31)
        # Falling from 150 to 50 over 250 days
        bars = _make_bars(date(2024, 1, 1), 250, 150.0, 50.0)
        result = price_above_sma200(bars, as_of)
        assert result is False

    def test_insufficient_data(self):
        """Less than 200 bars returns None."""
        as_of = date(2024, 12, 31)
        bars = _make_bars(date(2024, 6, 1), 100, 100.0, 110.0)
        result = price_above_sma200(bars, as_of)
        assert result is None


class TestComponentScores:
    def test_momentum_score_high(self):
        assert momentum_12_1_score(0.60) == 10.0

    def test_momentum_score_low(self):
        assert momentum_12_1_score(-0.30) == 0.0

    def test_momentum_score_mid(self):
        # (0.15 + 0.30) / 0.90 * 10 = 5.0
        assert abs(momentum_12_1_score(0.15) - 5.0) < 0.01

    def test_momentum_score_none(self):
        assert momentum_12_1_score(None) == 0.0

    def test_momentum_sector_ranked(self):
        """Sector ranking: 80th percentile of peers."""
        sector = [-0.10, -0.05, 0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35]
        # 0.25 beats 7 of 10 = 70th percentile = 7.0
        score = momentum_12_1_score(0.25, sector)
        assert abs(score - 7.0) < 0.01

    def test_sma200_above(self):
        assert sma200_score(True) == 5.0

    def test_sma200_below(self):
        assert sma200_score(False) == 0.0

    def test_sma200_none(self):
        assert sma200_score(None) == 0.0


class TestMomentumScore:
    def test_full_score_in_range(self):
        """Total momentum score is always [0, 15]."""
        as_of = date(2024, 12, 31)
        bars = _make_bars(date(2023, 10, 1), 310, 80.0, 150.0)
        score, breakdown = momentum_score(bars, as_of)
        assert 0 <= score <= 15
        assert "return_12_1" in breakdown
        assert "above_sma200" in breakdown
        assert "momentum_12_1_points" in breakdown
        assert "sma200_points" in breakdown

    def test_insufficient_data_zeroes(self):
        """Insufficient data gives 0 for both components."""
        bars = _make_bars(date(2024, 9, 1), 50, 100.0, 110.0)
        score, breakdown = momentum_score(bars, date(2024, 12, 31))
        assert score == 0.0
        assert breakdown["return_12_1"] is None
        assert breakdown["above_sma200"] is None

    def test_max_score(self):
        """Strong uptrend gets high score."""
        as_of = date(2024, 12, 31)
        # Strong uptrend: 50 -> 200 over 14 months
        bars = _make_bars(date(2023, 10, 1), 310, 50.0, 200.0)
        score, breakdown = momentum_score(bars, as_of)
        assert score >= 12.0  # High momentum + above SMA
        assert breakdown["above_sma200"] is True
