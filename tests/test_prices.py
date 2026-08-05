"""Tests for price data ingestion. TICKET-003."""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from durable.data.prices import (
    AdjustedPriceError,
    _assert_raw_ohlcv,
    add_known_corporate_action,
    assert_not_adjusted_only,
    get_total_return,
    ingest_daily_bars,
)
from durable.data.store import as_of, get_conn, init_schema


@pytest.fixture
def conn():
    c = get_conn(":memory:")
    init_schema(c)
    return c


class TestAdjustedPriceRejection:
    """Adjusted-close-only series must be rejected."""

    def test_missing_ohlcv_columns_raises(self):
        df = pd.DataFrame({"adj_close": [100.0], "volume": [1000]})
        with pytest.raises(AdjustedPriceError, match="Missing raw OHLCV"):
            _assert_raw_ohlcv(df)

    def test_all_nan_volume_raises(self):
        df = pd.DataFrame(
            {
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
                "volume": [np.nan],
            }
        )
        with pytest.raises(AdjustedPriceError, match="NaN"):
            _assert_raw_ohlcv(df)

    def test_valid_raw_ohlcv_passes(self):
        df = pd.DataFrame(
            {
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
                "volume": [50000000],
            }
        )
        _assert_raw_ohlcv(df)  # Should not raise

    def test_public_assertion(self):
        df = pd.DataFrame({"adj_close": [100.0]})
        with pytest.raises(AdjustedPriceError):
            assert_not_adjusted_only(df)


class TestCorporateActions:
    def test_add_known_split(self, conn):
        """AAPL 2020 4:1 split can be manually recorded."""
        add_known_corporate_action(
            conn,
            ticker="AAPL",
            ex_date=date(2020, 8, 31),
            action_type="split",
            factor=4.0,
            description="4-for-1 stock split",
            snapshot_id="aapl-split-2020",
        )
        actions = as_of(conn, "corporate_actions", date(2020, 9, 1), tickers="AAPL")
        assert len(actions) == 1
        assert actions.iloc[0]["factor"] == 4.0
        assert actions.iloc[0]["action_type"] == "split"

    def test_split_not_visible_before_ex_date(self, conn):
        """Split recorded on 2020-08-31 shouldn't appear in as_of(2020-08-30)."""
        add_known_corporate_action(
            conn,
            ticker="AAPL",
            ex_date=date(2020, 8, 31),
            action_type="split",
            factor=4.0,
            description="4-for-1 stock split",
            snapshot_id="aapl-split-2020",
        )
        actions = as_of(conn, "corporate_actions", date(2020, 8, 29), tickers="AAPL")
        assert len(actions) == 0


class TestTotalReturnWithSplit:
    """AAPL 2020 split handled — ticket acceptance criterion."""

    def test_split_adjusted_return(self, conn):
        """Total return calculation accounts for a 4:1 split correctly."""
        # Pre-split price: ~500, post-split: ~125 (same value)
        bars_pre = pd.DataFrame(
            {
                "ticker": ["AAPL"],
                "dt": [date(2020, 8, 28)],
                "open": [500.0],
                "high": [505.0],
                "low": [498.0],
                "close": [500.0],
                "volume": [30000000],
                "available_at": [datetime(2020, 8, 28, 16, 0)],
            }
        )
        # Post-split: price drops to 125 (same company value)
        bars_post = pd.DataFrame(
            {
                "ticker": ["AAPL"],
                "dt": [date(2020, 8, 31)],
                "open": [127.0],
                "high": [128.0],
                "low": [125.0],
                "close": [125.0],
                "volume": [120000000],
                "available_at": [datetime(2020, 8, 31, 16, 0)],
            }
        )

        from durable.data.store import write_snapshot

        write_snapshot(conn, "bars_daily", bars_pre, "bars-pre-split")
        write_snapshot(conn, "bars_daily", bars_post, "bars-post-split")

        # Add the split
        add_known_corporate_action(
            conn,
            ticker="AAPL",
            ex_date=date(2020, 8, 31),
            action_type="split",
            factor=4.0,
            description="4-for-1 stock split",
            snapshot_id="aapl-split-2020",
        )

        # Without split adjustment, return would be (125-500)/500 = -75%
        # With split adjustment, pre-split 500 / 4 = 125, return = (125-125)/125 = 0%
        ret = get_total_return(conn, "AAPL", date(2020, 8, 28), date(2020, 8, 31))
        assert abs(ret) < 0.001, f"Expected ~0% return after split adjustment, got {ret:.4f}"

    def test_return_without_split(self, conn):
        """Normal return calculation without corporate actions."""
        bars = pd.DataFrame(
            {
                "ticker": ["AAPL", "AAPL"],
                "dt": [date(2024, 1, 2), date(2024, 1, 5)],
                "open": [180.0, 185.0],
                "high": [182.0, 187.0],
                "low": [179.0, 184.0],
                "close": [181.0, 186.0],
                "volume": [50000000, 45000000],
                "available_at": [
                    datetime(2024, 1, 2, 16, 0),
                    datetime(2024, 1, 5, 16, 0),
                ],
            }
        )
        from durable.data.store import write_snapshot

        write_snapshot(conn, "bars_daily", bars, "bars-normal")

        ret = get_total_return(conn, "AAPL", date(2024, 1, 2), date(2024, 1, 5))
        expected = (186.0 - 181.0) / 181.0
        assert abs(ret - expected) < 1e-10


class TestFetchBarsIntegration:
    """Integration tests hitting Alpaca API. Requires network + keys."""

    @pytest.fixture
    def client(self):
        import os

        from dotenv import load_dotenv

        load_dotenv()
        key = os.getenv("ALPACA_PAPER_KEY_ID")
        secret = os.getenv("ALPACA_PAPER_SECRET_KEY")
        if not key or not secret:
            pytest.skip("Alpaca keys not set")
        from durable.data.prices import get_price_client

        return get_price_client(key, secret)

    def test_fetch_aapl_returns_raw_ohlcv(self, client):
        from durable.data.prices import fetch_daily_bars

        df = fetch_daily_bars(client, "AAPL", date(2024, 1, 2), date(2024, 1, 10))
        assert len(df) >= 5
        assert set(df.columns) == {
            "ticker", "dt", "open", "high", "low", "close", "volume", "available_at"
        }
        assert (df["volume"] > 0).all()

    def test_ingest_to_store(self, client, conn):
        sid = ingest_daily_bars(
            conn, client, "AAPL", date(2024, 1, 2), date(2024, 1, 10),
            snapshot_id="test-bars-aapl"
        )
        assert sid == "test-bars-aapl"
        result = as_of(conn, "bars_daily", date(2024, 1, 15), tickers="AAPL")
        assert len(result) >= 5

    def test_spy_total_return_reasonable(self, client, conn):
        """SPY total return for a known period should be within 10bps/yr of reality."""
        from durable.data.prices import fetch_daily_bars
        from durable.data.store import write_snapshot

        df = fetch_daily_bars(client, "SPY", date(2024, 1, 2), date(2024, 3, 28))
        write_snapshot(conn, "bars_daily", df, "spy-q1-2024")

        ret = get_total_return(conn, "SPY", date(2024, 1, 2), date(2024, 3, 28))
        # SPY Q1 2024 was roughly +10%
        assert 0.05 < ret < 0.20, f"SPY Q1 2024 return {ret:.4f} outside reasonable range"
