"""Tests for overlay tie-breakers. TICKET-009. Hand-computed fixtures."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from durable.factors.overlays import (
    compute_overlays,
    insider_overlay,
    institutional_overlay,
    political_overlay,
)


def _empty_form4() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "filed_at", "transaction_code", "is_officer_director",
            "amount_usd", "is_10b5_1", "shares_transacted", "insider_shares_held",
        ]
    )


def _empty_stock_act() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["filed_at", "ticker", "transaction_type", "has_committee_jurisdiction"]
    )


def _empty_13f() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["filed_at", "ticker", "manager_name", "is_top_10", "action"]
    )


class TestInsiderOverlay:
    def test_only_code_p_counts(self):
        """Only transaction code 'P' is considered — acceptance criterion."""
        as_of = date(2024, 6, 30)
        # Code 'F' (tax withholding) should be ignored
        df = pd.DataFrame([
            {"filed_at": "2024-03-15", "transaction_code": "F",
             "is_officer_director": True, "amount_usd": 500_000,
             "is_10b5_1": False, "shares_transacted": 0, "insider_shares_held": 10000},
            {"filed_at": "2024-04-01", "transaction_code": "F",
             "is_officer_director": True, "amount_usd": 300_000,
             "is_10b5_1": False, "shares_transacted": 0, "insider_shares_held": 10000},
        ])
        assert insider_overlay(df, as_of) == 0

    def test_two_officers_buy_250k(self):
        """+3: >=2 officers bought >= $250k aggregate, no 10b5-1."""
        as_of = date(2024, 6, 30)
        df = pd.DataFrame([
            {"filed_at": "2024-03-15", "transaction_code": "P",
             "is_officer_director": True, "amount_usd": 150_000,
             "is_10b5_1": False, "shares_transacted": 1000, "insider_shares_held": 50000},
            {"filed_at": "2024-04-01", "transaction_code": "P",
             "is_officer_director": True, "amount_usd": 120_000,
             "is_10b5_1": False, "shares_transacted": 800, "insider_shares_held": 30000},
        ])
        assert insider_overlay(df, as_of) == 3

    def test_one_officer_buy(self):
        """+1 for one officer buying."""
        as_of = date(2024, 6, 30)
        df = pd.DataFrame([
            {"filed_at": "2024-05-01", "transaction_code": "P",
             "is_officer_director": True, "amount_usd": 50_000,
             "is_10b5_1": False, "shares_transacted": 500, "insider_shares_held": 20000},
        ])
        assert insider_overlay(df, as_of) == 1

    def test_10b5_1_blocks_signal(self):
        """Simultaneous 10b5-1 plan neutralizes purchase signal."""
        as_of = date(2024, 6, 30)
        df = pd.DataFrame([
            {"filed_at": "2024-03-15", "transaction_code": "P",
             "is_officer_director": True, "amount_usd": 300_000,
             "is_10b5_1": False, "shares_transacted": 2000, "insider_shares_held": 50000},
            {"filed_at": "2024-04-01", "transaction_code": "P",
             "is_officer_director": True, "amount_usd": 200_000,
             "is_10b5_1": True, "shares_transacted": 1500, "insider_shares_held": 40000},
        ])
        assert insider_overlay(df, as_of) == 0

    def test_net_selling_negative(self):
        """-2 for net selling > 2% of insider-held shares."""
        as_of = date(2024, 6, 30)
        df = pd.DataFrame([
            {"filed_at": "2024-05-01", "transaction_code": "S",
             "is_officer_director": True, "amount_usd": 100_000,
             "is_10b5_1": False, "shares_transacted": 5000, "insider_shares_held": 100000},
        ])
        # 5000 / 100000 = 5% > 2%
        assert insider_overlay(df, as_of) == -2

    def test_outside_lookback_ignored(self):
        """Transactions > 6 months old are ignored."""
        as_of = date(2024, 6, 30)
        df = pd.DataFrame([
            {"filed_at": "2023-10-01", "transaction_code": "P",
             "is_officer_director": True, "amount_usd": 500_000,
             "is_10b5_1": False, "shares_transacted": 3000, "insider_shares_held": 50000},
        ])
        assert insider_overlay(df, as_of) == 0


class TestPoliticalOverlay:
    def test_uses_filed_at_not_traded_at(self):
        """Political overlay uses filed_at — acceptance criterion.

        A transaction traded before the window but filed within it should count.
        """
        as_of = date(2024, 6, 30)
        # Filed within 90 days
        df = pd.DataFrame([
            {"filed_at": "2024-05-01", "ticker": "AAPL",
             "transaction_type": "purchase", "has_committee_jurisdiction": True},
            {"filed_at": "2024-05-15", "ticker": "AAPL",
             "transaction_type": "purchase", "has_committee_jurisdiction": True},
            {"filed_at": "2024-06-01", "ticker": "AAPL",
             "transaction_type": "purchase", "has_committee_jurisdiction": False},
        ])
        result = political_overlay(df, as_of, "AAPL")
        assert result == 2  # >=3 bought, at least one with jurisdiction

    def test_three_buys_no_jurisdiction(self):
        """+1 without committee jurisdiction."""
        as_of = date(2024, 6, 30)
        df = pd.DataFrame([
            {"filed_at": "2024-05-01", "ticker": "MSFT",
             "transaction_type": "purchase", "has_committee_jurisdiction": False},
            {"filed_at": "2024-05-15", "ticker": "MSFT",
             "transaction_type": "purchase", "has_committee_jurisdiction": False},
            {"filed_at": "2024-06-01", "ticker": "MSFT",
             "transaction_type": "purchase", "has_committee_jurisdiction": False},
        ])
        assert political_overlay(df, as_of, "MSFT") == 1

    def test_three_sells_negative(self):
        """-1 if >=3 sold."""
        as_of = date(2024, 6, 30)
        df = pd.DataFrame([
            {"filed_at": "2024-05-01", "ticker": "XYZ",
             "transaction_type": "sale", "has_committee_jurisdiction": False},
            {"filed_at": "2024-05-15", "ticker": "XYZ",
             "transaction_type": "sale", "has_committee_jurisdiction": False},
            {"filed_at": "2024-06-01", "ticker": "XYZ",
             "transaction_type": "sale", "has_committee_jurisdiction": False},
        ])
        assert political_overlay(df, as_of, "XYZ") == -1

    def test_wrong_ticker_ignored(self):
        """Only transactions for the specified ticker count."""
        as_of = date(2024, 6, 30)
        df = pd.DataFrame([
            {"filed_at": "2024-05-01", "ticker": "GOOG",
             "transaction_type": "purchase", "has_committee_jurisdiction": True},
            {"filed_at": "2024-05-15", "ticker": "GOOG",
             "transaction_type": "purchase", "has_committee_jurisdiction": True},
            {"filed_at": "2024-06-01", "ticker": "GOOG",
             "transaction_type": "purchase", "has_committee_jurisdiction": True},
        ])
        assert political_overlay(df, as_of, "AAPL") == 0


class TestInstitutionalOverlay:
    def test_three_hold_top10_one_added(self):
        """+2: >=3 hold as top-10 AND >=1 added."""
        as_of = date(2024, 6, 30)
        df = pd.DataFrame([
            {"filed_at": "2024-05-15", "ticker": "AAPL", "manager_name": "Mgr1",
             "is_top_10": True, "action": "hold"},
            {"filed_at": "2024-05-15", "ticker": "AAPL", "manager_name": "Mgr2",
             "is_top_10": True, "action": "add"},
            {"filed_at": "2024-05-15", "ticker": "AAPL", "manager_name": "Mgr3",
             "is_top_10": True, "action": "hold"},
        ])
        assert institutional_overlay(df, as_of, "AAPL") == 2

    def test_three_hold_none_added(self):
        """+1: >=3 hold as top-10 but none added."""
        as_of = date(2024, 6, 30)
        df = pd.DataFrame([
            {"filed_at": "2024-05-15", "ticker": "MSFT", "manager_name": "Mgr1",
             "is_top_10": True, "action": "hold"},
            {"filed_at": "2024-05-15", "ticker": "MSFT", "manager_name": "Mgr2",
             "is_top_10": True, "action": "hold"},
            {"filed_at": "2024-05-15", "ticker": "MSFT", "manager_name": "Mgr3",
             "is_top_10": True, "action": "hold"},
        ])
        assert institutional_overlay(df, as_of, "MSFT") == 1

    def test_three_exited(self):
        """-1: >=3 exited."""
        as_of = date(2024, 6, 30)
        df = pd.DataFrame([
            {"filed_at": "2024-05-15", "ticker": "XYZ", "manager_name": "Mgr1",
             "is_top_10": False, "action": "exit"},
            {"filed_at": "2024-05-15", "ticker": "XYZ", "manager_name": "Mgr2",
             "is_top_10": False, "action": "exit"},
            {"filed_at": "2024-05-15", "ticker": "XYZ", "manager_name": "Mgr3",
             "is_top_10": False, "action": "exit"},
        ])
        assert institutional_overlay(df, as_of, "XYZ") == -1

    def test_uses_filed_at_not_period_end(self):
        """13F uses filed_at — acceptance criterion.

        A filing from the future (filed after as_of) must not be counted.
        """
        as_of = date(2024, 5, 1)
        df = pd.DataFrame([
            {"filed_at": "2024-05-15", "ticker": "AAPL", "manager_name": "Mgr1",
             "is_top_10": True, "action": "add"},
            {"filed_at": "2024-05-15", "ticker": "AAPL", "manager_name": "Mgr2",
             "is_top_10": True, "action": "add"},
            {"filed_at": "2024-05-15", "ticker": "AAPL", "manager_name": "Mgr3",
             "is_top_10": True, "action": "add"},
        ])
        # filed_at > as_of, so these should be filtered out
        assert institutional_overlay(df, as_of, "AAPL") == 0


class TestComputeOverlays:
    def test_outside_top40_gets_zero(self):
        """Outside top-40 base rank gets zero — acceptance criterion."""
        total, breakdown = compute_overlays(
            base_rank=41,
            form4_transactions=_empty_form4(),
            stock_act_transactions=_empty_stock_act(),
            holdings_13f=_empty_13f(),
            as_of=date(2024, 6, 30),
            ticker="AAPL",
        )
        assert total == 0
        assert breakdown["gated"] is True

    def test_inside_top40_computed(self):
        """Inside top-40 gets overlay computation."""
        form4 = pd.DataFrame([
            {"filed_at": "2024-05-01", "transaction_code": "P",
             "is_officer_director": True, "amount_usd": 300_000,
             "is_10b5_1": False, "shares_transacted": 2000, "insider_shares_held": 50000},
            {"filed_at": "2024-05-15", "transaction_code": "P",
             "is_officer_director": True, "amount_usd": 200_000,
             "is_10b5_1": False, "shares_transacted": 1500, "insider_shares_held": 40000},
        ])
        total, breakdown = compute_overlays(
            base_rank=10,
            form4_transactions=form4,
            stock_act_transactions=_empty_stock_act(),
            holdings_13f=_empty_13f(),
            as_of=date(2024, 6, 30),
            ticker="AAPL",
        )
        assert total == 3  # Two officers bought >= $250k
        assert breakdown["insider"] == 3
        assert breakdown["gated"] is False

    def test_total_clipped_to_5(self):
        """Total overlay clipped to ±5."""
        # Insider +3, Political +2, Institutional +2 = 7, clipped to 5
        form4 = pd.DataFrame([
            {"filed_at": "2024-05-01", "transaction_code": "P",
             "is_officer_director": True, "amount_usd": 300_000,
             "is_10b5_1": False, "shares_transacted": 2000, "insider_shares_held": 50000},
            {"filed_at": "2024-05-15", "transaction_code": "P",
             "is_officer_director": True, "amount_usd": 200_000,
             "is_10b5_1": False, "shares_transacted": 1500, "insider_shares_held": 40000},
        ])
        stock_act = pd.DataFrame([
            {"filed_at": "2024-05-01", "ticker": "AAPL",
             "transaction_type": "purchase", "has_committee_jurisdiction": True},
            {"filed_at": "2024-05-15", "ticker": "AAPL",
             "transaction_type": "purchase", "has_committee_jurisdiction": True},
            {"filed_at": "2024-06-01", "ticker": "AAPL",
             "transaction_type": "purchase", "has_committee_jurisdiction": False},
        ])
        holdings = pd.DataFrame([
            {"filed_at": "2024-05-15", "ticker": "AAPL", "manager_name": "Mgr1",
             "is_top_10": True, "action": "add"},
            {"filed_at": "2024-05-15", "ticker": "AAPL", "manager_name": "Mgr2",
             "is_top_10": True, "action": "hold"},
            {"filed_at": "2024-05-15", "ticker": "AAPL", "manager_name": "Mgr3",
             "is_top_10": True, "action": "hold"},
        ])
        total, breakdown = compute_overlays(
            base_rank=5,
            form4_transactions=form4,
            stock_act_transactions=stock_act,
            holdings_13f=holdings,
            as_of=date(2024, 6, 30),
            ticker="AAPL",
        )
        assert total == 5  # Clipped from 7
        assert breakdown["total_raw"] == 7
        assert breakdown["total_clipped"] == 5

    def test_each_overlay_in_own_column(self):
        """Each overlay has its own key in breakdown — acceptance criterion."""
        total, breakdown = compute_overlays(
            base_rank=1,
            form4_transactions=_empty_form4(),
            stock_act_transactions=_empty_stock_act(),
            holdings_13f=_empty_13f(),
            as_of=date(2024, 6, 30),
            ticker="TEST",
        )
        assert "insider" in breakdown
        assert "political" in breakdown
        assert "institutional" in breakdown
