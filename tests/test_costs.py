"""Tests for transaction cost model. TICKET-012. Hand-computed fixtures."""

from __future__ import annotations

from datetime import date

import pytest

from durable.backtest.costs import (
    TaxRates,
    TradeCost,
    compute_trade_cost,
    execution_cost_bps,
    execution_cost_dollars,
    holding_period_days,
    is_long_term,
    tax_cost,
    wash_sale_adjustment,
)


class TestExecutionCost:
    def test_multiplier_1x(self):
        """Base cost at 1x multiplier."""
        cost_1x = execution_cost_bps(100, 150.0, 1_000_000.0, multiplier=1.0)
        assert cost_1x > 0

    def test_multiplier_2x(self):
        """2x multiplier doubles the cost — acceptance criterion."""
        cost_1x = execution_cost_bps(100, 150.0, 1_000_000.0, multiplier=1.0)
        cost_2x = execution_cost_bps(100, 150.0, 1_000_000.0, multiplier=2.0)
        assert cost_2x == pytest.approx(cost_1x * 2.0)

    def test_multiplier_3x(self):
        """3x multiplier triples the cost — acceptance criterion."""
        cost_1x = execution_cost_bps(100, 150.0, 1_000_000.0, multiplier=1.0)
        cost_3x = execution_cost_bps(100, 150.0, 1_000_000.0, multiplier=3.0)
        assert cost_3x == pytest.approx(cost_1x * 3.0)

    def test_larger_trade_costs_more(self):
        """More shares (higher participation) costs more via sqrt impact."""
        cost_small = execution_cost_bps(100, 150.0, 1_000_000.0)
        cost_large = execution_cost_bps(10000, 150.0, 1_000_000.0)
        assert cost_large > cost_small

    def test_dollars_scales_with_notional(self):
        """Dollar cost proportional to notional."""
        cost = execution_cost_dollars(100, 200.0, 5_000_000.0)
        assert cost > 0
        # Notional = 100 * 200 = $20,000
        bps = execution_cost_bps(100, 200.0, 5_000_000.0)
        expected = 20_000 * bps / 10_000
        assert cost == pytest.approx(expected)


class TestTaxRates:
    def test_st_vs_lt_rates(self):
        """Short-term rate exceeds long-term rate — acceptance criterion."""
        rates = TaxRates()
        assert rates.effective_st > rates.effective_lt

    def test_holding_period_boundary(self):
        """365 days = short-term, 366 = long-term."""
        entry = date(2023, 1, 1)
        assert not is_long_term(entry, date(2023, 12, 31))  # 364 days
        assert not is_long_term(entry, date(2024, 1, 1))  # 365 days
        assert is_long_term(entry, date(2024, 1, 2))  # 366 days

    def test_tax_on_gain(self):
        """Tax only on gains, not losses."""
        rates = TaxRates()
        assert tax_cost(1000.0, date(2023, 1, 1), date(2024, 6, 1), rates) > 0
        assert tax_cost(-500.0, date(2023, 1, 1), date(2024, 6, 1), rates) == 0.0

    def test_st_tax_higher_than_lt(self):
        """Same gain taxed higher at ST rate."""
        rates = TaxRates()
        st_tax = tax_cost(10000.0, date(2024, 1, 1), date(2024, 6, 1), rates)
        lt_tax = tax_cost(10000.0, date(2023, 1, 1), date(2024, 6, 1), rates)
        assert st_tax > lt_tax


class TestWashSale:
    def test_defers_loss_into_basis(self):
        """Wash-sale defers loss into replacement lot's basis — acceptance criterion."""
        # Original sold at a $500 loss
        deferred, new_basis, inherited_date = wash_sale_adjustment(
            loss=-500.0,
            replacement_basis=3000.0,
            replacement_entry=date(2024, 3, 15),
            original_entry=date(2023, 6, 1),
        )
        assert deferred == 500.0
        assert new_basis == 3500.0  # 3000 + 500 deferred
        assert inherited_date == date(2023, 6, 1)  # Holding period inherited

    def test_holding_period_inherited(self):
        """Replacement lot inherits original holding period start."""
        _, _, inherited_date = wash_sale_adjustment(
            loss=-200.0,
            replacement_basis=1000.0,
            replacement_entry=date(2024, 7, 1),
            original_entry=date(2023, 3, 15),
        )
        assert inherited_date == date(2023, 3, 15)


class TestComputeTradeCost:
    def test_full_cost_computation(self):
        """Full cost includes execution + tax."""
        result = compute_trade_cost(
            ticker="AAPL",
            shares=100,
            price=150.0,
            entry_date=date(2023, 1, 15),
            exit_date=date(2024, 6, 15),
            cost_basis=12000.0,  # Gain = 15000 - 12000 = 3000
            adv=5_000_000.0,
        )
        assert isinstance(result, TradeCost)
        assert result.total_cost > 0
        assert result.tax_cost > 0  # Gain of $3000
        assert result.is_short_term is False  # > 365 days
        assert result.total_cost == pytest.approx(
            result.total_execution_cost + result.tax_cost
        )

    def test_short_term_trade(self):
        """Trade held < 1 year is short-term."""
        result = compute_trade_cost(
            ticker="MSFT",
            shares=50,
            price=300.0,
            entry_date=date(2024, 3, 1),
            exit_date=date(2024, 8, 1),
            cost_basis=14000.0,
            adv=10_000_000.0,
        )
        assert result.is_short_term is True

    def test_multiplier_sensitivity(self):
        """Cost multiplier scales execution cost."""
        base = compute_trade_cost(
            ticker="GOOG", shares=100, price=100.0,
            entry_date=date(2023, 1, 1), exit_date=date(2024, 6, 1),
            cost_basis=8000.0, adv=3_000_000.0, multiplier=1.0,
        )
        double = compute_trade_cost(
            ticker="GOOG", shares=100, price=100.0,
            entry_date=date(2023, 1, 1), exit_date=date(2024, 6, 1),
            cost_basis=8000.0, adv=3_000_000.0, multiplier=2.0,
        )
        assert double.total_execution_cost == pytest.approx(
            base.total_execution_cost * 2.0
        )
