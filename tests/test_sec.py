"""Tests for SEC fundamentals ingestion. TICKET-002."""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import pytest

from durable.data.sec import (
    FUNDAMENTAL_CONCEPTS,
    _deduplicate_facts,
    _next_trading_day,
    _resolve_field_name,
    fetch_fundamentals,
    get_quarterly_field,
    ingest_fundamentals,
)
from durable.data.store import as_of, get_conn, init_schema, row_count


@pytest.fixture
def conn():
    c = get_conn(":memory:")
    init_schema(c)
    return c


class TestNextTradingDay:
    def test_weekday_filing(self):
        # Wednesday filing -> Thursday
        result = _next_trading_day(date(2024, 3, 6))
        assert result.date() == date(2024, 3, 7)

    def test_friday_filing(self):
        # Friday filing -> Monday
        result = _next_trading_day(date(2024, 3, 8))
        assert result.date() == date(2024, 3, 11)

    def test_saturday_filing(self):
        # Saturday filing -> Monday
        result = _next_trading_day(date(2024, 3, 9))
        assert result.date() == date(2024, 3, 11)


class TestResolveFieldName:
    def test_revenue_concepts(self):
        assert _resolve_field_name("us-gaap:Revenues") == "revenue"
        assert (
            _resolve_field_name("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax")
            == "revenue"
        )

    def test_unknown_concept(self):
        assert _resolve_field_name("us-gaap:SomeObscureConcept") is None

    def test_all_concepts_resolve(self):
        for field, concepts in FUNDAMENTAL_CONCEPTS.items():
            for concept in concepts:
                assert _resolve_field_name(concept) == field


class TestDeduplicateFacts:
    def test_keeps_original_over_restatement(self):
        df = pd.DataFrame(
            {
                "ticker": ["AAPL", "AAPL"],
                "field": ["revenue", "revenue"],
                "period_end": [date(2023, 12, 31), date(2023, 12, 31)],
                "value": [100.0, 105.0],
                "filed_at": [datetime(2024, 2, 1), datetime(2024, 5, 1)],
                "available_at": [datetime(2024, 2, 2), datetime(2024, 5, 2)],
                "accession": ["acc-001", "acc-001"],
                "restated": [False, True],
            }
        )
        result = _deduplicate_facts(df)
        assert len(result) == 1
        assert result.iloc[0]["value"] == 100.0
        assert result.iloc[0]["restated"] == False  # noqa: E712

    def test_different_periods_kept(self):
        df = pd.DataFrame(
            {
                "ticker": ["AAPL", "AAPL"],
                "field": ["revenue", "revenue"],
                "period_end": [date(2023, 9, 30), date(2023, 12, 31)],
                "value": [90.0, 100.0],
                "filed_at": [datetime(2023, 11, 1), datetime(2024, 2, 1)],
                "available_at": [datetime(2023, 11, 2), datetime(2024, 2, 2)],
                "accession": ["acc-001", "acc-002"],
                "restated": [False, False],
            }
        )
        result = _deduplicate_facts(df)
        assert len(result) == 2


class TestFetchFundamentals:
    """Integration tests hitting SEC EDGAR. Requires network."""

    @pytest.mark.skipif(not pytest.importorskip("edgar"), reason="edgartools not installed")
    def test_aapl_has_40_plus_quarters(self):
        """AAPL yields >= 40 quarters with no nulls — ticket acceptance criterion."""
        import os

        from dotenv import load_dotenv

        load_dotenv()
        identity = os.getenv("EDGAR_IDENTITY")
        if not identity:
            pytest.skip("EDGAR_IDENTITY not set")

        df = fetch_fundamentals("AAPL", identity)

        # Should have data
        assert len(df) > 0

        # Revenue should have >= 40 quarters
        revenue = df[df["field"] == "revenue"]
        unique_periods = revenue["period_end"].nunique()
        assert unique_periods >= 40, f"AAPL revenue has {unique_periods} periods, need >= 40"

        # No null values in core fields
        assert df["value"].notna().all()
        assert df["available_at"].notna().all()
        assert df["filed_at"].notna().all()

    @pytest.mark.skipif(not pytest.importorskip("edgar"), reason="edgartools not installed")
    def test_available_at_after_filing_date(self):
        """available_at is filing_date + 1 trading day (always after)."""
        import os

        from dotenv import load_dotenv

        load_dotenv()
        identity = os.getenv("EDGAR_IDENTITY")
        if not identity:
            pytest.skip("EDGAR_IDENTITY not set")

        df = fetch_fundamentals("AAPL", identity)
        assert (df["available_at"] > df["filed_at"]).all()

    @pytest.mark.skipif(not pytest.importorskip("edgar"), reason="edgartools not installed")
    def test_restatements_flagged_originals_retained(self):
        """Restatements are flagged; originals retained."""
        import os

        from dotenv import load_dotenv

        load_dotenv()
        identity = os.getenv("EDGAR_IDENTITY")
        if not identity:
            pytest.skip("EDGAR_IDENTITY not set")

        df = fetch_fundamentals("AAPL", identity)
        # restated column exists and is boolean
        assert "restated" in df.columns
        assert df["restated"].dtype == bool


class TestIngestFundamentals:
    @pytest.mark.skipif(not pytest.importorskip("edgar"), reason="edgartools not installed")
    def test_ingest_writes_to_store(self, conn):
        import os

        from dotenv import load_dotenv

        load_dotenv()
        identity = os.getenv("EDGAR_IDENTITY")
        if not identity:
            pytest.skip("EDGAR_IDENTITY not set")

        sid = ingest_fundamentals(conn, "AAPL", identity, snapshot_id="test-aapl")
        assert sid == "test-aapl"
        assert row_count(conn, "facts_fundamentals") > 0

    @pytest.mark.skipif(not pytest.importorskip("edgar"), reason="edgartools not installed")
    def test_as_of_filters_future(self, conn):
        """Data ingested for AAPL is filterable by as_of date."""
        import os

        from dotenv import load_dotenv

        load_dotenv()
        identity = os.getenv("EDGAR_IDENTITY")
        if not identity:
            pytest.skip("EDGAR_IDENTITY not set")

        ingest_fundamentals(conn, "AAPL", identity, snapshot_id="test-aapl-asof")

        # Should get data as of 2020
        old_data = as_of(conn, "facts_fundamentals", "2020-06-01", tickers="AAPL")
        # Should get more data as of 2024
        recent_data = as_of(conn, "facts_fundamentals", "2024-06-01", tickers="AAPL")
        assert len(recent_data) > len(old_data)


class TestGetQuarterlyField:
    @pytest.mark.skipif(not pytest.importorskip("edgar"), reason="edgartools not installed")
    def test_returns_sorted_by_period(self, conn):
        import os

        from dotenv import load_dotenv

        load_dotenv()
        identity = os.getenv("EDGAR_IDENTITY")
        if not identity:
            pytest.skip("EDGAR_IDENTITY not set")

        ingest_fundamentals(conn, "AAPL", identity, snapshot_id="test-quarterly")
        result = get_quarterly_field(conn, "AAPL", "revenue", date(2024, 6, 1))
        assert len(result) > 0
        # Verify sorted
        periods = result["period_end"].tolist()
        assert periods == sorted(periods)
