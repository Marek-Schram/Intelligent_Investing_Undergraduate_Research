"""Tests for Alpaca broker adapter. TICKET-015. Safety-critical."""

from __future__ import annotations

from pathlib import Path

import pytest

from durable.execution.broker import (
    KillSwitchError,
    MissingLotIdsError,
    NotionalLimitError,
    OrderResult,
    PaperOnlyError,
    ReconcileFailedError,
    assert_safe_to_trade,
    submit_limit_order,
)


class TestAssertSafeToTrade:
    def test_paper_api_asserted(self):
        """Asserts 'paper-api' in URL — acceptance criterion."""
        # Should pass with paper-api URL
        assert_safe_to_trade("https://paper-api.alpaca.markets")

    def test_live_url_without_flag_raises(self):
        """Live URL without live_trading_approved raises PaperOnlyError."""
        with pytest.raises(PaperOnlyError):
            assert_safe_to_trade(
                "https://api.alpaca.markets",
                live_trading_approved=False,
            )

    def test_live_url_with_flag_passes(self):
        """Live URL WITH flag passes (requires the flag — acceptance criterion)."""
        assert_safe_to_trade(
            "https://api.alpaca.markets",
            live_trading_approved=True,
        )

    def test_kill_exits_before_auth(self, tmp_path):
        """KILL file exits before any authentication — acceptance criterion."""
        kill_file = tmp_path / "KILL"
        kill_file.write_text("stop")
        with pytest.raises(KillSwitchError):
            assert_safe_to_trade(
                "https://paper-api.alpaca.markets",
                kill_file=kill_file,
            )

    def test_reconcile_failed_blocks(self, tmp_path):
        """RECONCILE_FAILED blocks submit."""
        recon_file = tmp_path / "RECONCILE_FAILED"
        recon_file.write_text("mismatch detected")
        with pytest.raises(ReconcileFailedError):
            assert_safe_to_trade(
                "https://paper-api.alpaca.markets",
                reconcile_failed_file=recon_file,
            )


class TestSubmitLimitOrder:
    def test_dry_run_default(self):
        """dry_run=True is the default — no accidental live trades."""
        result = submit_limit_order(
            symbol="AAPL",
            qty=10,
            side="buy",
            limit_price=150.0,
        )
        assert result.status == "dry_run"
        assert isinstance(result, OrderResult)

    def test_sell_without_lot_ids_raises(self):
        """Sells without lot_ids raise MissingLotIdsError — acceptance criterion."""
        with pytest.raises(MissingLotIdsError):
            submit_limit_order(
                symbol="AAPL",
                qty=10,
                side="sell",
                limit_price=150.0,
                lot_ids=None,
            )

    def test_sell_with_lot_ids_passes(self):
        """Sell with explicit lot_ids succeeds."""
        result = submit_limit_order(
            symbol="AAPL",
            qty=10,
            side="sell",
            limit_price=150.0,
            lot_ids=["lot-001", "lot-002"],
        )
        assert result.status == "dry_run"
        assert result.lot_ids == ["lot-001", "lot-002"]

    def test_no_shorts(self):
        """Only 'buy' and 'sell' allowed — no short selling."""
        with pytest.raises(ValueError, match="no shorts"):
            submit_limit_order(
                symbol="AAPL",
                qty=10,
                side="short",
                limit_price=150.0,
            )

    def test_notional_limit(self):
        """Order exceeding notional limit raises."""
        with pytest.raises(NotionalLimitError):
            submit_limit_order(
                symbol="BRK.A",
                qty=1,
                side="buy",
                limit_price=600_000.0,
                max_notional=50_000.0,
            )

    def test_re_validates_independently(self):
        """submit re-validates safety (does not trust the proposal) — acceptance criterion.

        submit_limit_order calls assert_safe_to_trade internally, so a live
        URL without the flag is caught even if the caller already checked.
        """
        with pytest.raises(PaperOnlyError):
            submit_limit_order(
                symbol="AAPL",
                qty=10,
                side="buy",
                limit_price=150.0,
                base_url="https://api.alpaca.markets",
                live_trading_approved=False,
            )


class TestChaosReconcilable:
    def test_order_result_has_enough_info_to_reconcile(self):
        """OrderResult contains all fields needed for reconciliation."""
        result = submit_limit_order(
            symbol="MSFT",
            qty=5,
            side="buy",
            limit_price=300.0,
        )
        # Must have: symbol, qty, side, limit_price, status
        assert result.symbol == "MSFT"
        assert result.qty == 5
        assert result.side == "buy"
        assert result.limit_price == 300.0
        assert result.status in ("dry_run", "submitted", "filled", "rejected")

    def test_sell_result_has_lot_ids(self):
        """Sell results carry lot_ids for reconciliation."""
        result = submit_limit_order(
            symbol="GOOG",
            qty=3,
            side="sell",
            limit_price=100.0,
            lot_ids=["lot-A"],
        )
        assert result.lot_ids == ["lot-A"]
