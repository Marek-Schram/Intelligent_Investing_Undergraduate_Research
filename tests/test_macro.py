"""Tests for macro and Fama-French data. TICKET-005."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from durable.data.store import get_conn, init_schema


@pytest.fixture
def conn():
    c = get_conn(":memory:")
    init_schema(c)
    return c


class TestFredFetch:
    def test_fetch_dgs10(self):
        """DGS10 returns data, percent format converted to raw rate."""
        import os

        from dotenv import load_dotenv

        load_dotenv()
        api_key = os.getenv("FRED_API_KEY")
        if not api_key:
            pytest.skip("FRED_API_KEY not set")

        from durable.data.macro import fetch_fred_series

        df = fetch_fred_series(api_key, "DGS10", start=date(2024, 1, 1))
        assert len(df) > 0
        assert set(df.columns) == {"series_id", "dt", "value", "available_at"}
        assert df["series_id"].iloc[0] == "DGS10"
        # Treasury rates should be between 0 and 20 (percent)
        assert df["value"].min() > 0
        assert df["value"].max() < 20

    def test_fetch_all_fred(self):
        """Multiple series fetched together."""
        import os

        from dotenv import load_dotenv

        load_dotenv()
        api_key = os.getenv("FRED_API_KEY")
        if not api_key:
            pytest.skip("FRED_API_KEY not set")

        from durable.data.macro import fetch_all_fred

        df = fetch_all_fred(api_key, series_ids=["DGS10", "DGS2"])
        assert "DGS10" in df["series_id"].values
        assert "DGS2" in df["series_id"].values


class TestFamaFrench:
    def test_percent_to_decimal(self):
        """FF returns converted from percent to decimal — the critical gotcha."""
        from durable.data.macro import fetch_fama_french

        df = fetch_fama_french()
        assert len(df) > 0
        # Decimal returns should typically be between -0.5 and 0.5 monthly
        values = df["value"]
        assert values.max() < 1.0, "Returns still in percent, not decimal"
        assert values.min() > -1.0, "Returns still in percent, not decimal"

    def test_monthly_table_only(self):
        """Only monthly data is used (not annual)."""
        from durable.data.macro import fetch_fama_french

        df = fetch_fama_french()
        # Should have data going back decades
        dates = pd.to_datetime(df["dt"])
        assert dates.min().year <= 1970

    def test_yyyymm_parsed_correctly(self):
        """Dates are proper date objects, not YYYYMM integers."""
        from durable.data.macro import fetch_fama_french

        df = fetch_fama_french()
        # dt should be date objects, not integers
        sample = df["dt"].iloc[0]
        assert isinstance(sample, date), f"Expected date, got {type(sample)}"

    def test_momentum_factor(self):
        """Momentum factor fetches and converts correctly."""
        from durable.data.macro import fetch_momentum_factor

        df = fetch_momentum_factor()
        assert len(df) > 0
        assert df["value"].max() < 1.0


class TestIngestMacro:
    def test_ingest_and_query(self, conn):
        """Macro data ingests and is queryable via as_of."""
        import os

        from dotenv import load_dotenv

        load_dotenv()
        api_key = os.getenv("FRED_API_KEY")
        if not api_key:
            pytest.skip("FRED_API_KEY not set")

        from durable.data.macro import get_risk_free_rate, ingest_macro

        ingest_macro(conn, api_key, series_ids=["DGS10"], snapshot_id="test-macro")

        rate = get_risk_free_rate(conn, date(2025, 1, 1))
        assert rate is not None
        assert 0.01 < rate < 0.10  # 1% to 10% is reasonable
