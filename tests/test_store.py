"""Tests for the point-in-time DuckDB store. TICKET-001."""

from __future__ import annotations

import time
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from durable.data.store import (
    DuplicateSnapshotError,
    LeakageError,
    as_of,
    get_conn,
    init_schema,
    list_snapshots,
    row_count,
    write_snapshot,
)


@pytest.fixture
def conn():
    """In-memory DuckDB connection with schema initialized."""
    c = get_conn(":memory:")
    init_schema(c)
    return c


def _make_fundamentals(ticker: str, available_at: str, n: int = 1) -> pd.DataFrame:
    """Helper: create a fundamentals DataFrame with n rows."""
    return pd.DataFrame(
        {
            "ticker": [ticker] * n,
            "field": ["revenue"] * n,
            "period_end": [date(2023, 12, 31)] * n,
            "value": [1000.0] * n,
            "filed_at": [datetime.fromisoformat(available_at)] * n,
            "available_at": [datetime.fromisoformat(available_at)] * n,
            "accession": ["0001234-23-000001"] * n,
            "restated": [False] * n,
        }
    )


class TestSchemaIdempotent:
    def test_init_schema_twice_no_error(self, conn):
        init_schema(conn)
        init_schema(conn)
        assert row_count(conn, "facts_fundamentals") == 0

    def test_all_tables_created(self, conn):
        tables = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchdf()
        expected = {
            "facts_fundamentals",
            "bars_daily",
            "corporate_actions",
            "macro_series",
            "insider_txns",
            "political_txns",
            "institutional_holdings",
            "short_interest",
            "credit_spreads",
            "filing_extractions",
            "factor_ic",
            "firewall_violations",
            "tax_lots",
            "snapshots",
        }
        actual = set(tables["table_name"].tolist())
        assert expected.issubset(actual)


class TestWriteSnapshot:
    def test_append_rows(self, conn):
        df = _make_fundamentals("AAPL", "2024-02-15T10:00:00")
        write_snapshot(conn, "facts_fundamentals", df, "snap-001")
        assert row_count(conn, "facts_fundamentals") == 1

    def test_duplicate_snapshot_raises(self, conn):
        df = _make_fundamentals("AAPL", "2024-02-15T10:00:00")
        write_snapshot(conn, "facts_fundamentals", df, "snap-001")
        with pytest.raises(DuplicateSnapshotError):
            write_snapshot(conn, "facts_fundamentals", df, "snap-001")

    def test_different_snapshots_append(self, conn):
        df1 = _make_fundamentals("AAPL", "2024-02-15T10:00:00")
        df2 = _make_fundamentals("MSFT", "2024-03-01T10:00:00")
        write_snapshot(conn, "facts_fundamentals", df1, "snap-001")
        write_snapshot(conn, "facts_fundamentals", df2, "snap-002")
        assert row_count(conn, "facts_fundamentals") == 2

    def test_snapshot_registered(self, conn):
        df = _make_fundamentals("AAPL", "2024-02-15T10:00:00")
        write_snapshot(conn, "facts_fundamentals", df, "snap-001", description="test")
        snaps = list_snapshots(conn)
        assert len(snaps) == 1
        assert snaps.iloc[0]["snapshot_id"] == "snap-001"
        assert snaps.iloc[0]["table_name"] == "facts_fundamentals"
        assert snaps.iloc[0]["row_count"] == 1

    def test_empty_df_raises(self, conn):
        df = pd.DataFrame(columns=["ticker", "field", "period_end", "value",
                                    "filed_at", "available_at", "accession", "restated"])
        with pytest.raises(ValueError, match="empty"):
            write_snapshot(conn, "facts_fundamentals", df, "snap-empty")

    def test_unknown_table_raises(self, conn):
        df = _make_fundamentals("AAPL", "2024-02-15T10:00:00")
        with pytest.raises(ValueError, match="Unknown table"):
            write_snapshot(conn, "nonexistent_table", df, "snap-001")

    def test_df_with_snapshot_id_column_raises(self, conn):
        df = _make_fundamentals("AAPL", "2024-02-15T10:00:00")
        df["snapshot_id"] = "sneaky"
        with pytest.raises(ValueError, match="must not contain"):
            write_snapshot(conn, "facts_fundamentals", df, "snap-001")


class TestAsOf:
    def test_filters_future_data(self, conn):
        df_past = _make_fundamentals("AAPL", "2024-01-15T10:00:00")
        df_future = _make_fundamentals("AAPL", "2024-06-15T10:00:00")
        write_snapshot(conn, "facts_fundamentals", df_past, "snap-past")
        write_snapshot(conn, "facts_fundamentals", df_future, "snap-future")

        result = as_of(conn, "facts_fundamentals", "2024-03-01")
        assert len(result) == 1
        assert result.iloc[0]["ticker"] == "AAPL"

    def test_as_of_with_date_object(self, conn):
        df = _make_fundamentals("AAPL", "2024-01-15T10:00:00")
        write_snapshot(conn, "facts_fundamentals", df, "snap-001")

        result = as_of(conn, "facts_fundamentals", date(2024, 3, 1))
        assert len(result) == 1

    def test_as_of_with_datetime_object(self, conn):
        df = _make_fundamentals("AAPL", "2024-01-15T10:00:00")
        write_snapshot(conn, "facts_fundamentals", df, "snap-001")

        result = as_of(conn, "facts_fundamentals", datetime(2024, 3, 1, 12, 0, 0))
        assert len(result) == 1

    def test_ticker_filter(self, conn):
        df_aapl = _make_fundamentals("AAPL", "2024-01-15T10:00:00")
        df_msft = _make_fundamentals("MSFT", "2024-01-15T10:00:00")
        write_snapshot(conn, "facts_fundamentals", df_aapl, "snap-aapl")
        write_snapshot(conn, "facts_fundamentals", df_msft, "snap-msft")

        result = as_of(conn, "facts_fundamentals", "2024-12-31", tickers="AAPL")
        assert len(result) == 1
        assert result.iloc[0]["ticker"] == "AAPL"

    def test_ticker_filter_list(self, conn):
        for ticker, sid in [("AAPL", "s1"), ("MSFT", "s2"), ("GOOG", "s3")]:
            df = _make_fundamentals(ticker, "2024-01-15T10:00:00")
            write_snapshot(conn, "facts_fundamentals", df, sid)

        result = as_of(conn, "facts_fundamentals", "2024-12-31", tickers=["AAPL", "GOOG"])
        assert set(result["ticker"].tolist()) == {"AAPL", "GOOG"}

    def test_empty_result_valid(self, conn):
        df = _make_fundamentals("AAPL", "2024-06-15T10:00:00")
        write_snapshot(conn, "facts_fundamentals", df, "snap-001")

        result = as_of(conn, "facts_fundamentals", "2024-01-01")
        assert len(result) == 0

    def test_as_of_returns_snapshot_id_column(self, conn):
        df = _make_fundamentals("AAPL", "2024-01-15T10:00:00")
        write_snapshot(conn, "facts_fundamentals", df, "snap-001")
        result = as_of(conn, "facts_fundamentals", "2024-12-31")
        assert "snapshot_id" in result.columns


class TestLeakageAssertion:
    def test_leakage_error_is_assertion_error(self):
        assert issubclass(LeakageError, AssertionError)

    def test_assert_catches_future_rows(self, conn):
        """Directly test that a corrupted result would be caught."""
        from durable.data.store import _assert_no_future_fast

        df = pd.DataFrame({"available_at": [datetime(2025, 1, 1)]})
        with pytest.raises(LeakageError, match="future"):
            _assert_no_future_fast(df, datetime(2024, 6, 1), "test_table")


class TestPerformance:
    def test_one_million_rows_under_200ms(self, conn):
        """1M rows filtered in < 200ms — the acceptance criterion."""
        rng = np.random.default_rng(42)
        n = 1_000_000
        tickers = [f"T{i:04d}" for i in range(500)]

        df = pd.DataFrame(
            {
                "ticker": rng.choice(tickers, n),
                "field": "revenue",
                "period_end": date(2023, 12, 31),
                "value": rng.normal(1000, 200, n),
                "filed_at": pd.Timestamp("2024-01-15 10:00:00"),
                "available_at": pd.to_datetime(
                    rng.integers(
                        int(datetime(2020, 1, 1).timestamp()),
                        int(datetime(2024, 12, 31).timestamp()),
                        n,
                    ),
                    unit="s",
                ),
                "accession": "0001234-23-000001",
                "restated": False,
            }
        )

        write_snapshot(conn, "facts_fundamentals", df, "perf-test")
        assert row_count(conn, "facts_fundamentals") == n

        start = time.perf_counter()
        result = as_of(conn, "facts_fundamentals", "2022-06-15")
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert len(result) > 0
        assert elapsed_ms < 200, f"as_of took {elapsed_ms:.1f}ms, must be < 200ms"


class TestListSnapshots:
    def test_filter_by_table(self, conn):
        df = _make_fundamentals("AAPL", "2024-01-15T10:00:00")
        write_snapshot(conn, "facts_fundamentals", df, "snap-001")

        bars = pd.DataFrame(
            {
                "ticker": ["AAPL"],
                "dt": [date(2024, 1, 15)],
                "open": [180.0],
                "high": [182.0],
                "low": [179.0],
                "close": [181.0],
                "volume": [50000000],
                "available_at": [datetime(2024, 1, 16, 10, 0, 0)],
            }
        )
        write_snapshot(conn, "bars_daily", bars, "snap-bars-001")

        fund_snaps = list_snapshots(conn, table="facts_fundamentals")
        assert len(fund_snaps) == 1
        assert fund_snaps.iloc[0]["snapshot_id"] == "snap-001"


class TestGetConn:
    def test_memory_connection(self):
        c = get_conn(":memory:")
        assert c is not None
        c.close()

    def test_none_gives_memory(self):
        c = get_conn(None)
        assert c is not None
        c.close()

    def test_file_connection(self, tmp_path):
        db_path = tmp_path / "test.duckdb"
        c = get_conn(db_path)
        init_schema(c)
        assert db_path.exists()
        c.close()

    def test_creates_parent_dirs(self, tmp_path):
        db_path = tmp_path / "nested" / "dir" / "test.duckdb"
        c = get_conn(db_path)
        assert db_path.parent.exists()
        c.close()
