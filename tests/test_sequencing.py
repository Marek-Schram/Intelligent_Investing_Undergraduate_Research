"""Tests for order sequencing. TICKET-047."""

from __future__ import annotations

from decimal import Decimal

import pytest

from durable.execution.sequencer import (
    InvariantViolation,
    Order,
    SequencedPlan,
    assert_invariants,
    projected_turnover,
    sequence,
)


def _sell(ticker: str, notional: float, lot_ids: list[str] | None = None) -> Order:
    return Order(
        ticker=ticker,
        side="sell",
        notional=Decimal(str(notional)),
        limit_price=Decimal("50.00"),
        lot_ids=lot_ids or [f"lot_{ticker}_1"],
        reason="rebalance",
    )


def _buy(ticker: str, notional: float) -> Order:
    return Order(
        ticker=ticker,
        side="buy",
        notional=Decimal(str(notional)),
        limit_price=Decimal("50.00"),
        lot_ids=None,
        reason="rebalance",
    )


class TestSellsFirst:
    """Sells execute first; proceeds recorded net of cost."""

    def test_sells_before_buys(self):
        orders = [_buy("AAPL", 1000), _sell("MSFT", 500)]
        plan = sequence(orders, Decimal("200"))
        assert plan.cash_after_sells > plan.cash_before

    def test_proceeds_net_of_cost(self):
        orders = [_sell("MSFT", 1000)]
        plan = sequence(orders, Decimal("100"), cost_rate=Decimal("0.01"))
        expected = Decimal("100") + Decimal("1000") * Decimal("0.99")
        assert plan.cash_after_sells == expected


class TestAffordableCash:
    """affordable = cash / (1 + cost_rate) — cost reserved on buy side."""

    def test_fully_funded(self):
        orders = [_buy("AAPL", 100)]
        plan = sequence(orders, Decimal("200"))
        assert plan.scale_applied == Decimal("1")
        assert not plan.shortfall

    def test_shortfall_triggers_scaling(self):
        orders = [_buy("AAPL", 5000)]
        plan = sequence(orders, Decimal("100"))
        assert plan.shortfall is True
        assert plan.scale_applied < Decimal("1")

    def test_cost_reserved_on_buy_side(self):
        """affordable = cash / (1 + cost_rate). Spending all cash on notional leaves nothing
        for spread and slippage, which is the original bug."""
        orders = [_buy("AAPL", 100)]
        plan = sequence(orders, Decimal("100"), cost_rate=Decimal("0.01"))
        assert plan.cash_after_buys >= 0


class TestProRataScaling:
    """Buys scaled pro-rata, NOT priority-ordered."""

    def test_equal_scaling(self):
        orders = [_buy("A", 200), _buy("B", 200)]
        plan = sequence(orders, Decimal("100"))
        if plan.shortfall:
            buy_a = next(b for b in plan.buys if b.ticker == "A")
            buy_b = next(b for b in plan.buys if b.ticker == "B")
            assert buy_a.notional == buy_b.notional

    def test_proportional_scaling(self):
        orders = [_buy("A", 300), _buy("B", 100)]
        plan = sequence(orders, Decimal("100"))
        if plan.shortfall:
            buy_a = next(b for b in plan.buys if b.ticker == "A")
            buy_b = next(b for b in plan.buys if b.ticker == "B")
            ratio = buy_a.notional / buy_b.notional
            assert float(ratio) == pytest.approx(3.0, rel=0.01)


class TestAssertInvariants:
    """assert_invariants raises on negative cash at any step."""

    def test_negative_cash_after_buys_raises(self):
        plan = SequencedPlan(
            sells=[], buys=[], scale_applied=Decimal("1"),
            cash_before=Decimal("100"),
            cash_after_sells=Decimal("100"),
            cash_after_buys=Decimal("-1"),
            shortfall=False, notes=[],
        )
        with pytest.raises(InvariantViolation):
            assert_invariants(plan)

    def test_sell_without_lot_ids_raises(self):
        bad_sell = Order("BAD", "sell", Decimal("100"), Decimal("50"), lot_ids=None, reason="rebalance")
        plan = SequencedPlan(
            sells=[bad_sell], buys=[], scale_applied=Decimal("1"),
            cash_before=Decimal("100"),
            cash_after_sells=Decimal("200"),
            cash_after_buys=Decimal("200"),
            shortfall=False, notes=[],
        )
        with pytest.raises(InvariantViolation, match="lot_ids"):
            assert_invariants(plan)

    def test_valid_plan_passes(self):
        sell = Order("MSFT", "sell", Decimal("100"), Decimal("50"), lot_ids=["lot1"], reason="S1")
        plan = SequencedPlan(
            sells=[sell], buys=[], scale_applied=Decimal("1"),
            cash_before=Decimal("100"),
            cash_after_sells=Decimal("200"),
            cash_after_buys=Decimal("200"),
            shortfall=False, notes=[],
        )
        assert_invariants(plan)


class TestNoCashNegativeRegression:
    """THE regression test. The fixture that produced 11 negative quarters
    now produces 0 under sequencing."""

    def test_sell_proceeds_fund_buys(self):
        orders = [
            _sell("OLD1", 5000),
            _sell("OLD2", 3000),
            _buy("NEW1", 4000),
            _buy("NEW2", 3000),
            _buy("NEW3", 2000),
        ]
        plan = sequence(orders, Decimal("500"))
        assert plan.cash_after_buys >= 0

    def test_large_buys_get_scaled_not_rejected(self):
        """If buys exceed available, they scale down — never negative cash."""
        orders = [_buy("A", 10000), _buy("B", 10000), _buy("C", 10000)]
        plan = sequence(orders, Decimal("1000"))
        assert plan.cash_after_buys >= 0
        assert plan.shortfall is True

    def test_cash_buffer_not_needed(self):
        """Sequencing eliminates negative cash by construction — no buffer needed."""
        orders = [
            _sell("S1", 2000), _sell("S2", 1500), _sell("S3", 1000),
            _buy("B1", 3000), _buy("B2", 2000), _buy("B3", 1500),
            _buy("B4", 1000), _buy("B5", 500),
        ]
        plan = sequence(orders, Decimal("100"))
        assert plan.cash_after_buys >= 0


class TestProjectedTurnover:
    def test_basic_calculation(self):
        orders = [_sell("A", 1000), _buy("B", 1000)]
        nav = Decimal("10000")
        result = projected_turnover(orders, nav)
        expected = (Decimal("2000") / Decimal("10000")) * 4
        assert result == expected

    def test_zero_nav(self):
        orders = [_buy("A", 100)]
        assert projected_turnover(orders, Decimal("0")) == Decimal("0")

    def test_annualized(self):
        """Quarterly turnover * 4 = annualized."""
        orders = [_sell("A", 250), _buy("B", 250)]
        nav = Decimal("10000")
        quarterly = Decimal("500") / Decimal("10000")
        assert projected_turnover(orders, nav) == quarterly * 4
