"""Tests for portfolio reconciliation. TICKET-016."""

from __future__ import annotations

import pandas as pd
import pytest

from durable.execution.reconcile import (
    ReconciliationMismatchError,
    assert_reconciled,
    reconcile,
)


def _pos(data: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(data)


class TestReconcile:
    def test_matching_positions(self):
        """Exact match passes."""
        internal = _pos(
            [
                {"ticker": "AAPL", "shares": 100.0},
                {"ticker": "MSFT", "shares": 50.0},
            ]
        )
        broker = _pos(
            [
                {"ticker": "AAPL", "shares": 100.0},
                {"ticker": "MSFT", "shares": 50.0},
            ]
        )
        result = reconcile(internal, broker)
        assert result.matches is True
        assert result.mismatches == []

    def test_internal_only_mismatch(self):
        """Ticker in internal but not broker."""
        internal = _pos(
            [
                {"ticker": "AAPL", "shares": 100.0},
                {"ticker": "GOOG", "shares": 30.0},
            ]
        )
        broker = _pos([{"ticker": "AAPL", "shares": 100.0}])
        result = reconcile(internal, broker)
        assert result.matches is False
        assert "GOOG" in result.internal_only

    def test_broker_only_mismatch(self):
        """Ticker in broker but not internal."""
        internal = _pos([{"ticker": "AAPL", "shares": 100.0}])
        broker = _pos(
            [
                {"ticker": "AAPL", "shares": 100.0},
                {"ticker": "TSLA", "shares": 20.0},
            ]
        )
        result = reconcile(internal, broker)
        assert result.matches is False
        assert "TSLA" in result.broker_only

    def test_share_count_mismatch(self):
        """Same ticker, different share count."""
        internal = _pos([{"ticker": "AAPL", "shares": 100.0}])
        broker = _pos([{"ticker": "AAPL", "shares": 95.0}])
        result = reconcile(internal, broker)
        assert result.matches is False
        assert len(result.share_diffs) == 1
        assert result.share_diffs[0]["diff"] == pytest.approx(5.0)

    def test_within_tolerance_passes(self):
        """Tiny fractional difference within tolerance passes."""
        internal = _pos([{"ticker": "AAPL", "shares": 100.0}])
        broker = _pos([{"ticker": "AAPL", "shares": 100.0005}])
        result = reconcile(internal, broker)
        assert result.matches is True


class TestAssertReconciled:
    def test_mismatch_blocks_submit(self, tmp_path):
        """Mismatch blocks submit — acceptance criterion."""
        internal = _pos([{"ticker": "AAPL", "shares": 100.0}])
        broker = _pos([{"ticker": "AAPL", "shares": 50.0}])
        recon_file = tmp_path / "RECONCILE_FAILED"

        with pytest.raises(ReconciliationMismatchError):
            assert_reconciled(internal, broker, reconcile_failed_path=recon_file)

        # RECONCILE_FAILED file should be created
        assert recon_file.exists()
        content = recon_file.read_text()
        assert "Mismatch" in content

    def test_match_removes_stale_flag(self, tmp_path):
        """Successful reconciliation removes stale RECONCILE_FAILED."""
        recon_file = tmp_path / "RECONCILE_FAILED"
        recon_file.write_text("old mismatch")

        internal = _pos([{"ticker": "AAPL", "shares": 100.0}])
        broker = _pos([{"ticker": "AAPL", "shares": 100.0}])

        result = assert_reconciled(internal, broker, reconcile_failed_path=recon_file)
        assert result.matches is True
        assert not recon_file.exists()

    def test_empty_portfolios_match(self, tmp_path):
        """Two empty portfolios reconcile."""
        internal = pd.DataFrame(columns=["ticker", "shares"])
        broker = pd.DataFrame(columns=["ticker", "shares"])
        recon_file = tmp_path / "RECONCILE_FAILED"

        result = assert_reconciled(internal, broker, reconcile_failed_path=recon_file)
        assert result.matches is True
