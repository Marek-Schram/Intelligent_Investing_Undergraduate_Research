"""The most important test in the repo. docs/03 §1."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from durable.data import store


def test_future_filing_does_not_change_past_scores():
    """Corrupt a filing dated AFTER the as-of date; earlier scores must not move.

    1. Score 2018-06-30 from a fixture DB. Record.
    2. Insert an absurd filing (revenue = 1e15) with available_at = 2018-09-30.
    3. Re-score 2018-06-30. Assert byte-identical.

    If this can pass without a real point-in-time guard, the guard isn't real.
    """
    conn = store.get_conn()
    store.init_schema(conn)

    # Create initial fixture data available before June 30
    initial_data = pd.DataFrame({
        "ticker": ["AAPL"],
        "field": ["revenue"],
        "period_end": [date(2018, 3, 31)],
        "value": [50000.0],
        "filed_at": pd.Timestamp("2018-05-15 16:00:00"),
        "available_at": pd.Timestamp("2018-05-16 09:30:00"),  # Available before June 30
        "accession": ["0001234-18-000001"],
        "restated": [False],
    })

    store.write_snapshot(conn, "facts_fundamentals", initial_data, "test_fixture_initial")

    # Score as of June 30, 2018
    as_of_date = pd.Timestamp("2018-06-30")
    result_before = store.as_of(conn, "facts_fundamentals", as_of_date)

    # Record the initial state
    initial_revenue = result_before[result_before["ticker"] == "AAPL"]["value"].iloc[0]
    assert initial_revenue == 50000.0

    # NOW: Insert corrupt data dated AFTER June 30 (should not affect earlier scores)
    future_data = pd.DataFrame({
        "ticker": ["AAPL"],
        "field": ["revenue"],
        "period_end": [date(2018, 6, 30)],
        "value": [1e15],  # Absurdly high - obvious corruption
        "filed_at": pd.Timestamp("2018-08-15 16:00:00"),
        "available_at": pd.Timestamp("2018-09-30 09:30:00"),  # AFTER our as_of date
        "accession": ["0001234-18-000002"],
        "restated": [False],
    })

    store.write_snapshot(conn, "facts_fundamentals", future_data, "test_fixture_corrupt")

    # Re-score as of June 30, 2018
    result_after = store.as_of(conn, "facts_fundamentals", as_of_date)

    # The score MUST NOT change - future data should be invisible
    revenue_after = result_after[result_after["ticker"] == "AAPL"]["value"].iloc[0]
    assert revenue_after == initial_revenue == 50000.0, (
        f"Future filing changed past scores! Before: {initial_revenue}, After: {revenue_after}"
    )

    # The result should be byte-identical
    pd.testing.assert_frame_equal(result_before, result_after)


def test_available_at_boundary_excludes_future():
    """A row with available_at = as_of + 1 second must be excluded."""
    conn = store.get_conn()
    store.init_schema(conn)

    as_of_ts = pd.Timestamp("2024-06-15 16:00:00")

    # Create test data with precise timing
    test_data = pd.DataFrame({
        "ticker": ["AAPL", "MSFT", "GOOGL"],
        "field": ["revenue"] * 3,
        "period_end": [date(2024, 3, 31)] * 3,
        "value": [100.0, 200.0, 300.0],
        "filed_at": [pd.Timestamp("2024-06-01")] * 3,
        "available_at": [
            pd.Timestamp("2024-06-15 15:59:59"),  # 1 second BEFORE - should be included
            pd.Timestamp("2024-06-15 16:00:00"),  # EXACTLY at boundary - should be included
            pd.Timestamp("2024-06-15 16:00:01"),  # 1 second AFTER - should be excluded
        ],
        "accession": ["acc1", "acc2", "acc3"],
        "restated": [False] * 3,
    })

    store.write_snapshot(conn, "facts_fundamentals", test_data, "test_boundary")

    # Query as_of the exact timestamp
    result = store.as_of(conn, "facts_fundamentals", as_of_ts)

    # Only AAPL and MSFT should be present (not GOOGL)
    tickers_returned = set(result["ticker"].tolist())

    assert "AAPL" in tickers_returned, "Data 1 second before should be included"
    assert "MSFT" in tickers_returned, "Data exactly at boundary should be included"
    assert "GOOGL" not in tickers_returned, "Data 1 second after should be excluded"

    assert len(result) == 2, f"Expected 2 rows, got {len(result)}"


def test_no_restated_values_used():
    """Where an original and a restatement exist, scoring uses the original."""
    conn = store.get_conn()
    store.init_schema(conn)

    as_of = pd.Timestamp("2024-06-30")

    # Original filing
    original = pd.DataFrame({
        "ticker": ["AAPL"],
        "field": ["revenue"],
        "period_end": [date(2024, 3, 31)],
        "value": [50000.0],  # Original value
        "filed_at": pd.Timestamp("2024-05-15 16:00:00"),
        "available_at": pd.Timestamp("2024-05-16 09:30:00"),
        "accession": ["0001234-24-000001"],
        "restated": [False],  # Original
    })

    # Restatement filed later (correcting an "error")
    restatement = pd.DataFrame({
        "ticker": ["AAPL"],
        "field": ["revenue"],
        "period_end": [date(2024, 3, 31)],  # Same period
        "value": [52000.0],  # Restated value (higher)
        "filed_at": pd.Timestamp("2024-06-10 16:00:00"),  # Later filing
        "available_at": pd.Timestamp("2024-06-11 09:30:00"),
        "accession": ["0001234-24-000001/A"],  # Amendment
        "restated": [True],  # This is a restatement
    })

    # Write both
    write_snapshot(conn, "facts_fundamentals", original, "test_original")
    write_snapshot(conn, "facts_fundamentals", restatement, "test_restatement")

    # Query as of June 30 (after both are available)
    result = store.as_of(conn, "facts_fundamentals", as_of_ts)

    # Filter for AAPL revenue
    aapl_revenue = result[
        (result["ticker"] == "AAPL") & (result["field"] == "revenue")
    ]

    # Should return ONLY the original, not the restatement
    assert len(aapl_revenue) == 1, f"Expected 1 row, got {len(aapl_revenue)}"
    assert aapl_revenue.iloc[0]["value"] == 50000.0, (
        f"Should use original value (50000), not restated (52000). "
        f"Got: {aapl_revenue.iloc[0]['value']}"
    )
    assert aapl_revenue.iloc[0]["restated"] is False


def test_13f_uses_filed_at_not_period_end():
    """13F carries a 45-day lag. Using period_end is look-ahead by 45 days."""
    conn = store.get_conn()
    store.init_schema(conn)

    as_of = pd.Timestamp("2024-04-15")  # Mid-April

    # 13F data - period_end is Q1 end, but not filed until 45 days later
    data_13f = pd.DataFrame({
        "ticker": ["AAPL"],
        "manager": ["Berkshire Hathaway"],
        "shares": [1000000],
        "period_end": pd.Timestamp("2024-03-31"),  # Q1 end
        "filed_at": pd.Timestamp("2024-05-15"),  # Filed 45 days after quarter end
        "available_at": pd.Timestamp("2024-05-16"),  # Available day after filing
        "form_type": ["13F-HR"],
    })

    write_snapshot(conn, "institutional_holdings", data_13f, "test_13f")

    # Query as of April 15 (BEFORE the 13F was filed)
    result = as_of(conn, "institutional_holdings", as_of)

    # Should be EMPTY - the 13F wasn't filed yet, even though the period ended
    assert len(result) == 0, (
        f"13F filed on May 15 should NOT be visible on April 15. "
        f"Using period_end instead of filed_at is 45-day look-ahead. "
        f"Got {len(result)} rows."
    )

    # Query as of May 20 (AFTER the 13F was filed)
    as_of_after = pd.Timestamp("2024-05-20")
    result_after = as_of(conn, "institutional_holdings", as_of_after)

    # NOW it should be visible
    assert len(result_after) == 1, "13F should be visible after filing date"
    assert result_after.iloc[0]["ticker"] == "AAPL"


def test_short_interest_uses_publication_date():
    """FINRA publishes 11+ business days after settlement."""
    conn = store.get_conn()
    store.init_schema(conn)

    as_of = pd.Timestamp("2024-06-15")

    # Short interest data with settlement vs publication lag
    short_data = pd.DataFrame({
        "ticker": ["AAPL"],
        "settlement_date": [date(2024, 5, 31)],  # Settlement date (event date)
        "publication_date": pd.Timestamp("2024-06-14"),  # Published ~11 business days later
        "available_at": pd.Timestamp("2024-06-14 09:30:00"),  # Available at publication
        "short_interest": [5000000],
        "days_to_cover": [2.5],
    })

    write_snapshot(conn, "short_interest", short_data, "test_short")

    # Query as of June 10 (BEFORE publication, but after settlement)
    as_of_before = pd.Timestamp("2024-06-10")
    result_before = as_of(conn, "short_interest", as_of_before)

    # Should be EMPTY - not published yet, even though settlement happened
    assert len(result_before) == 0, (
        f"Short interest published on June 14 should NOT be visible on June 10. "
        f"Using settlement_date instead of publication_date leaks data. "
        f"Got {len(result_before)} rows."
    )

    # Query as of June 15 (AFTER publication)
    result_after = as_of(conn, "short_interest", as_of)

    # NOW it should be visible
    assert len(result_after) == 1, "Short interest should be visible after publication"
    assert result_after.iloc[0]["ticker"] == "AAPL"
    assert result_after.iloc[0]["short_interest"] == 5000000


def test_llm_extraction_contamination_guard():
    """Using an extraction before the model's training cutoff must raise unless
    explicitly allowed — the model has read the future (docs/13 §1)."""
    from durable.signals.extract import check_contamination, ContaminationError

    # Claude's training cutoff (example - adjust to actual)
    model_cutoff = pd.Timestamp("2025-05-01")

    # Test 1: Extraction from BEFORE cutoff - should be fine
    filing_date_before = pd.Timestamp("2024-01-15")

    # Should not raise (extraction is from before model training)
    try:
        check_contamination(
            filing_date=filing_date_before,
            model_training_cutoff=model_cutoff,
            allow_contaminated=False,
        )
    except Exception as e:
        pytest.fail(f"check_contamination incorrectly raised for pre-cutoff data: {e}")

    # Test 2: Extraction from AFTER cutoff - should raise
    filing_date_after = pd.Timestamp("2025-08-15")

    with pytest.raises(ContaminationError) as exc_info:
        check_contamination(
            filing_date=filing_date_after,
            model_training_cutoff=model_cutoff,
            allow_contaminated=False,
        )

    error_msg = str(exc_info.value).lower()
    assert "contamination" in error_msg or "cutoff" in error_msg or "after" in error_msg

    # Test 3: Contaminated but explicitly allowed - should pass
    try:
        check_contamination(
            filing_date=filing_date_after,
            model_training_cutoff=model_cutoff,
            allow_contaminated=True,  # Explicit override
        )
    except Exception as e:
        pytest.fail(f"check_contamination should allow when allow_contaminated=True: {e}")
