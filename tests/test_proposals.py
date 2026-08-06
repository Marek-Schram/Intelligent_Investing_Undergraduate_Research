"""Tests for rebalance proposal generation. TICKET-010. Hand-computed fixtures."""

from __future__ import annotations

from datetime import date

import pandas as pd

from durable.execution.propose import (
    RebalanceProposal,
    SellRule,
    _check_sell_rules,
    _is_wash_sale_blocked,
    generate_proposal,
)


def _make_scores(tickers_data: list[dict]) -> pd.DataFrame:
    """Helper to create a scores DataFrame."""
    return pd.DataFrame(tickers_data)


def _make_holdings(tickers_data: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(tickers_data)


def _empty_sales() -> pd.DataFrame:
    return pd.DataFrame(columns=["ticker", "sale_date", "realized_gain"])


class TestSellRules:
    def test_s1_two_consecutive_out_of_buffer(self):
        """S1: rank out of top 80 at TWO consecutive rebalances."""
        rules = _check_sell_rules(
            ticker="WEAK",
            current_rank=85,
            prev_rank=82,
            is_excluded=False,
            implied_growth=0.10,
            position_weight=0.05,
            sector_weight=0.20,
            has_corporate_action=False,
        )
        assert SellRule.S1_RANK_OUT in rules

    def test_s1_not_fired_first_time(self):
        """S1 does NOT fire on first occurrence."""
        rules = _check_sell_rules(
            ticker="SLIP",
            current_rank=85,
            prev_rank=50,  # Was inside buffer last time
            is_excluded=False,
            implied_growth=0.10,
            position_weight=0.05,
            sector_weight=0.20,
            has_corporate_action=False,
        )
        assert SellRule.S1_RANK_OUT not in rules

    def test_s2_exclusion_flag(self):
        """S2: any exclusion-level flag triggers sell."""
        rules = _check_sell_rules(
            ticker="FRAUD",
            current_rank=10,
            prev_rank=10,
            is_excluded=True,
            implied_growth=0.10,
            position_weight=0.05,
            sector_weight=0.20,
            has_corporate_action=False,
        )
        assert SellRule.S2_EXCLUSION_FLAG in rules

    def test_s3_implied_growth_too_high(self):
        """S3: implied growth > 25%."""
        rules = _check_sell_rules(
            ticker="HYPE",
            current_rank=5,
            prev_rank=5,
            is_excluded=False,
            implied_growth=0.30,
            position_weight=0.05,
            sector_weight=0.20,
            has_corporate_action=False,
        )
        assert SellRule.S3_IMPLIED_GROWTH in rules

    def test_s4_concentration(self):
        """S4: position > 12%."""
        rules = _check_sell_rules(
            ticker="BIG",
            current_rank=1,
            prev_rank=1,
            is_excluded=False,
            implied_growth=0.05,
            position_weight=0.13,
            sector_weight=0.20,
            has_corporate_action=False,
        )
        assert SellRule.S4_CONCENTRATION in rules

    def test_s5_corporate_action(self):
        """S5: corporate action."""
        rules = _check_sell_rules(
            ticker="MERGE",
            current_rank=5,
            prev_rank=5,
            is_excluded=False,
            implied_growth=0.05,
            position_weight=0.05,
            sector_weight=0.20,
            has_corporate_action=True,
        )
        assert SellRule.S5_CORPORATE_ACTION in rules

    def test_every_sell_cites_rule(self):
        """Every sell must cite exactly which S1-S5 rule fired — acceptance criterion."""
        rules = _check_sell_rules(
            ticker="TEST",
            current_rank=90,
            prev_rank=90,
            is_excluded=True,
            implied_growth=0.30,
            position_weight=0.05,
            sector_weight=0.20,
            has_corporate_action=False,
        )
        # Multiple rules can fire simultaneously
        assert len(rules) >= 2
        for rule in rules:
            assert isinstance(rule, SellRule)
            assert rule.value.startswith("S")


class TestWashSale:
    def test_wash_sale_blocks_repurchase(self):
        """Wash-sale blocks a loss-repurchase — acceptance criterion."""
        recent_sales = pd.DataFrame(
            [
                {"ticker": "AAPL", "sale_date": "2024-06-15", "realized_gain": -500.0},
            ]
        )
        # 10 days after sale — within 30-day window
        blocked = _is_wash_sale_blocked("AAPL", recent_sales, date(2024, 6, 25))
        assert blocked is True

    def test_wash_sale_not_blocked_outside_window(self):
        """Outside 61-day window is fine."""
        recent_sales = pd.DataFrame(
            [
                {"ticker": "AAPL", "sale_date": "2024-03-01", "realized_gain": -500.0},
            ]
        )
        # 120 days later — well outside window
        blocked = _is_wash_sale_blocked("AAPL", recent_sales, date(2024, 7, 1))
        assert blocked is False

    def test_wash_sale_gain_not_blocked(self):
        """Gain sales don't create wash-sale risk."""
        recent_sales = pd.DataFrame(
            [
                {"ticker": "MSFT", "sale_date": "2024-06-15", "realized_gain": 1000.0},
            ]
        )
        blocked = _is_wash_sale_blocked("MSFT", recent_sales, date(2024, 6, 25))
        assert blocked is False

    def test_wash_sale_wrong_ticker(self):
        """Wash sale only applies to the same ticker."""
        recent_sales = pd.DataFrame(
            [
                {"ticker": "AAPL", "sale_date": "2024-06-15", "realized_gain": -500.0},
            ]
        )
        blocked = _is_wash_sale_blocked("MSFT", recent_sales, date(2024, 6, 25))
        assert blocked is False


class TestGenerateProposal:
    def test_blank_mistake_line(self):
        """Proposal has a blank 'mistake' line — acceptance criterion."""
        scores = _make_scores(
            [
                {
                    "ticker": "AAPL",
                    "composite_score": 85,
                    "rank": 1,
                    "is_excluded": False,
                    "implied_growth": 0.05,
                    "sector": "Tech",
                    "has_corporate_action": False,
                },
            ]
        )
        holdings = _make_holdings(
            [
                {
                    "ticker": "AAPL",
                    "shares": 100,
                    "weight": 0.05,
                    "sector": "Tech",
                    "lot_ids": ["lot-1"],
                },
            ]
        )
        proposal = generate_proposal(
            scores=scores,
            current_holdings=holdings,
            prev_ranks=None,
            recent_sales=_empty_sales(),
            as_of=date(2024, 8, 16),
        )
        assert isinstance(proposal, RebalanceProposal)
        assert proposal.mistakes == ""
        assert hasattr(proposal, "mistakes")

    def test_sell_cites_rule(self):
        """Every sell in the proposal cites its S1-S5 rule."""
        scores = _make_scores(
            [
                {
                    "ticker": "WEAK",
                    "composite_score": 20,
                    "rank": 85,
                    "is_excluded": False,
                    "implied_growth": 0.05,
                    "sector": "Tech",
                    "has_corporate_action": False,
                },
            ]
        )
        holdings = _make_holdings(
            [
                {
                    "ticker": "WEAK",
                    "shares": 50,
                    "weight": 0.04,
                    "sector": "Tech",
                    "lot_ids": ["lot-2"],
                },
            ]
        )
        prev_ranks = pd.DataFrame([{"ticker": "WEAK", "rank": 90}])

        proposal = generate_proposal(
            scores=scores,
            current_holdings=holdings,
            prev_ranks=prev_ranks,
            recent_sales=_empty_sales(),
            as_of=date(2024, 8, 16),
        )

        sells = [t for t in proposal.trades if t.action == "sell"]
        assert len(sells) == 1
        assert sells[0].sell_rule is not None
        assert sells[0].sell_rule == SellRule.S1_RANK_OUT

    def test_wash_sale_blocks_buy(self):
        """Wash-sale blocked tickers appear in wash_sale_blocks, not in trades."""
        scores = _make_scores(
            [
                {
                    "ticker": "AAPL",
                    "composite_score": 90,
                    "rank": 1,
                    "is_excluded": False,
                    "implied_growth": 0.05,
                    "sector": "Tech",
                    "has_corporate_action": False,
                },
                {
                    "ticker": "MSFT",
                    "composite_score": 85,
                    "rank": 2,
                    "is_excluded": False,
                    "implied_growth": 0.04,
                    "sector": "Tech",
                    "has_corporate_action": False,
                },
            ]
        )
        recent_sales = pd.DataFrame(
            [
                {"ticker": "AAPL", "sale_date": "2024-08-01", "realized_gain": -200.0},
            ]
        )

        proposal = generate_proposal(
            scores=scores,
            current_holdings=pd.DataFrame(
                columns=["ticker", "shares", "weight", "sector", "lot_ids"]
            ),
            prev_ranks=None,
            recent_sales=recent_sales,
            as_of=date(2024, 8, 16),
        )

        buy_tickers = [t.ticker for t in proposal.trades if t.action == "buy"]
        assert "AAPL" not in buy_tickers
        assert "AAPL" in proposal.wash_sale_blocks
        assert "MSFT" in buy_tickers

    def test_holds_retained_in_buffer(self):
        """Holdings within buffer rank are retained."""
        scores = _make_scores(
            [
                {
                    "ticker": "HOLD",
                    "composite_score": 50,
                    "rank": 60,
                    "is_excluded": False,
                    "implied_growth": 0.08,
                    "sector": "Tech",
                    "has_corporate_action": False,
                },
            ]
        )
        holdings = _make_holdings(
            [
                {
                    "ticker": "HOLD",
                    "shares": 100,
                    "weight": 0.05,
                    "sector": "Tech",
                    "lot_ids": ["lot-3"],
                },
            ]
        )
        prev_ranks = pd.DataFrame([{"ticker": "HOLD", "rank": 55}])

        proposal = generate_proposal(
            scores=scores,
            current_holdings=holdings,
            prev_ranks=prev_ranks,
            recent_sales=_empty_sales(),
            as_of=date(2024, 8, 16),
        )

        assert "HOLD" in proposal.holds
        sell_tickers = [t.ticker for t in proposal.trades if t.action == "sell"]
        assert "HOLD" not in sell_tickers
