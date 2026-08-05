"""Tests for after-tax return calculation. TICKET-037. Hand-computed fixtures."""

from __future__ import annotations

from decimal import Decimal

import pytest

from durable.tax.after_tax import (
    AfterTaxResult,
    CarryforwardResult,
    LossCarryforward,
    RealizedGain,
    TaxAlphaResult,
    UseNowVsCarryResult,
    after_tax_return,
    apply_carryforward,
    model_use_now_vs_carry,
    tax_alpha_vs_fifo,
)


class TestAfterTaxReturn:
    """After-tax reported alongside pre-tax — acceptance criterion."""

    def test_basic_after_tax_with_gains(self):
        """Hand-computed: $100k portfolio grows to $110k with $5k ST gain realized.
        ST tax = 5000 * 0.37 = $1,850.
        Pre-tax return = 10%.
        After-tax return = (110000 - 1850 - 100000) / 100000 = 8.15%.
        """
        gains = [
            RealizedGain(
                proceeds=Decimal("15000"),
                cost_basis=Decimal("10000"),
                is_long_term=False,
            ),
        ]
        result = after_tax_return(
            gains=gains,
            beginning_value=Decimal("100000"),
            ending_value=Decimal("110000"),
        )

        assert isinstance(result, AfterTaxResult)
        assert result.pre_tax_return == Decimal("0.1")
        assert result.after_tax_return == Decimal("0.0815")
        assert result.tax_drag == Decimal("0.0185")
        assert result.st_taxes_paid == Decimal("1850")
        assert result.lt_taxes_paid == Decimal("0")

    def test_long_term_gains_lower_tax(self):
        """LT gains taxed at 20%: $10k LT gain -> $2,000 tax."""
        gains = [
            RealizedGain(
                proceeds=Decimal("20000"),
                cost_basis=Decimal("10000"),
                is_long_term=True,
            ),
        ]
        result = after_tax_return(
            gains=gains,
            beginning_value=Decimal("100000"),
            ending_value=Decimal("110000"),
        )

        assert result.lt_taxes_paid == Decimal("2000")
        assert result.st_taxes_paid == Decimal("0")
        assert result.after_tax_return == Decimal("0.08")

    def test_losses_incur_no_tax(self):
        """Realized losses do not generate a tax bill."""
        gains = [
            RealizedGain(
                proceeds=Decimal("8000"),
                cost_basis=Decimal("12000"),
                is_long_term=False,
            ),
        ]
        result = after_tax_return(
            gains=gains,
            beginning_value=Decimal("100000"),
            ending_value=Decimal("105000"),
        )

        assert result.st_taxes_paid == Decimal("0")
        assert result.lt_taxes_paid == Decimal("0")
        assert result.after_tax_return == result.pre_tax_return

    def test_mixed_st_and_lt_gains(self):
        """Mix of ST and LT gains: each taxed at its own rate.
        ST gain: $3,000 -> tax = 3000 * 0.37 = $1,110.
        LT gain: $7,000 -> tax = 7000 * 0.20 = $1,400.
        Total tax = $2,510.
        """
        gains = [
            RealizedGain(
                proceeds=Decimal("13000"),
                cost_basis=Decimal("10000"),
                is_long_term=False,
            ),
            RealizedGain(
                proceeds=Decimal("17000"),
                cost_basis=Decimal("10000"),
                is_long_term=True,
            ),
        ]
        result = after_tax_return(
            gains=gains,
            beginning_value=Decimal("200000"),
            ending_value=Decimal("220000"),
        )

        assert result.st_taxes_paid == Decimal("1110")
        assert result.lt_taxes_paid == Decimal("1400")
        total_tax = Decimal("2510")
        assert result.tax_drag == total_tax / Decimal("200000")

    def test_zero_beginning_value_raises(self):
        """Cannot divide by zero beginning value."""
        with pytest.raises(ValueError, match="beginning_value must be positive"):
            after_tax_return(
                gains=[],
                beginning_value=Decimal("0"),
                ending_value=Decimal("100"),
            )

    def test_custom_rates(self):
        """Custom rates override defaults."""
        gains = [
            RealizedGain(
                proceeds=Decimal("20000"),
                cost_basis=Decimal("10000"),
                is_long_term=False,
            ),
        ]
        result = after_tax_return(
            gains=gains,
            beginning_value=Decimal("100000"),
            ending_value=Decimal("110000"),
            st_rate=Decimal("0.25"),
            lt_rate=Decimal("0.15"),
        )

        # $10k ST gain at 25% = $2,500 tax
        assert result.st_taxes_paid == Decimal("2500")

    def test_pre_tax_alongside_after_tax(self):
        """Both pre-tax and after-tax are always available in result."""
        gains = [
            RealizedGain(
                proceeds=Decimal("11000"),
                cost_basis=Decimal("10000"),
                is_long_term=True,
            ),
        ]
        result = after_tax_return(
            gains=gains,
            beginning_value=Decimal("50000"),
            ending_value=Decimal("55000"),
        )

        # Pre-tax = (55000-50000)/50000 = 0.10
        assert result.pre_tax_return == Decimal("0.1")
        # Tax = 1000 * 0.20 = 200
        # After-tax = (55000 - 200 - 50000) / 50000 = 0.096
        assert result.after_tax_return == Decimal("0.096")


class TestTaxAlphaVsFifo:
    """Tax alpha positive when optimal selection beats FIFO — acceptance criterion."""

    def test_optimal_beats_fifo(self):
        """Optimal sells LT lots (20% rate) instead of ST lots (37% rate).
        Same total gain but different tax treatment.

        FIFO sells the ST lot first: $5,000 gain at 37% = $1,850.
        Optimal sells the LT lot: $5,000 gain at 20% = $1,000.
        Alpha = $850.
        """
        fifo_gains = [
            RealizedGain(
                proceeds=Decimal("15000"),
                cost_basis=Decimal("10000"),
                is_long_term=False,
            ),
        ]
        optimal_gains = [
            RealizedGain(
                proceeds=Decimal("15000"),
                cost_basis=Decimal("10000"),
                is_long_term=True,
            ),
        ]
        result = tax_alpha_vs_fifo(
            optimal_gains=optimal_gains,
            fifo_gains=fifo_gains,
            portfolio_value=Decimal("100000"),
        )

        assert isinstance(result, TaxAlphaResult)
        assert result.fifo_tax == Decimal("1850")
        assert result.optimal_tax == Decimal("1000")
        assert result.tax_alpha == Decimal("850")
        assert result.tax_alpha > Decimal("0")
        # 850 / 100000 * 10000 = 85 bps
        assert result.alpha_bps == Decimal("85")

    def test_alpha_zero_when_identical(self):
        """No alpha when both methods produce same result."""
        gains = [
            RealizedGain(
                proceeds=Decimal("12000"),
                cost_basis=Decimal("10000"),
                is_long_term=True,
            ),
        ]
        result = tax_alpha_vs_fifo(
            optimal_gains=gains,
            fifo_gains=gains,
            portfolio_value=Decimal("50000"),
        )

        assert result.tax_alpha == Decimal("0")
        assert result.alpha_bps == Decimal("0")

    def test_multiple_lots_alpha(self):
        """Multiple lots: optimal picks the lowest-tax combination.

        FIFO: sells 2 ST lots at $3k gain each = 6000 * 0.37 = $2,220.
        Optimal: sells 1 LT lot at $6k gain = 6000 * 0.20 = $1,200.
        Alpha = $1,020.
        """
        fifo_gains = [
            RealizedGain(
                proceeds=Decimal("13000"),
                cost_basis=Decimal("10000"),
                is_long_term=False,
            ),
            RealizedGain(
                proceeds=Decimal("13000"),
                cost_basis=Decimal("10000"),
                is_long_term=False,
            ),
        ]
        optimal_gains = [
            RealizedGain(
                proceeds=Decimal("16000"),
                cost_basis=Decimal("10000"),
                is_long_term=True,
            ),
        ]
        result = tax_alpha_vs_fifo(
            optimal_gains=optimal_gains,
            fifo_gains=fifo_gains,
            portfolio_value=Decimal("200000"),
        )

        assert result.fifo_tax == Decimal("2220")
        assert result.optimal_tax == Decimal("1200")
        assert result.tax_alpha == Decimal("1020")

    def test_invalid_portfolio_value_raises(self):
        """Portfolio value must be positive."""
        with pytest.raises(ValueError, match="portfolio_value must be positive"):
            tax_alpha_vs_fifo(
                optimal_gains=[],
                fifo_gains=[],
                portfolio_value=Decimal("0"),
            )


class TestCarryforwardCap:
    """Carryforward caps at $3,000 per year — acceptance criterion."""

    def test_ordinary_income_offset_capped_at_3000(self):
        """Even with $50k carryforward, only $3,000 offsets ordinary income per year."""
        cf = LossCarryforward(
            short_term=Decimal("30000"),
            long_term=Decimal("20000"),
        )
        result = apply_carryforward(
            carryforward=cf,
            st_gains=Decimal("0"),
            lt_gains=Decimal("0"),
        )

        assert isinstance(result, CarryforwardResult)
        assert result.ordinary_income_offset == Decimal("3000")
        # Remaining = 50000 - 3000 = 47000
        remaining = result.remaining_carryforward
        assert remaining.total == Decimal("47000")

    def test_carryforward_fully_offsets_gains_no_cap(self):
        """Carryforward offsets gains dollar-for-dollar (no $3k cap on gains)."""
        cf = LossCarryforward(
            short_term=Decimal("10000"),
            long_term=Decimal("0"),
        )
        result = apply_carryforward(
            carryforward=cf,
            st_gains=Decimal("8000"),
            lt_gains=Decimal("0"),
        )

        # $10k ST carryforward offsets $8k ST gains -> $2k remaining
        assert result.taxable_gains_after == Decimal("0")
        # Remaining $2k: $2k < $3k cap, so all offsets ordinary
        assert result.ordinary_income_offset == Decimal("2000")
        assert result.remaining_carryforward.total == Decimal("0")

    def test_cap_with_partial_gain_offset(self):
        """Cap applies only to the excess after offsetting gains."""
        cf = LossCarryforward(
            short_term=Decimal("20000"),
            long_term=Decimal("0"),
        )
        result = apply_carryforward(
            carryforward=cf,
            st_gains=Decimal("5000"),
            lt_gains=Decimal("0"),
        )

        # $20k offsets $5k gains -> $15k remaining
        # Of that $15k, only $3k offsets ordinary income
        assert result.taxable_gains_after == Decimal("0")
        assert result.ordinary_income_offset == Decimal("3000")
        # Remaining = 15000 - 3000 = 12000
        assert result.remaining_carryforward.short_term == Decimal("12000")


class TestCarryforwardPersistence:
    """Carryforward persists across years — acceptance criterion."""

    def test_multi_year_carryforward(self):
        """Simulate 3 years of carryforward with no gains."""
        cf = LossCarryforward(
            short_term=Decimal("10000"),
            long_term=Decimal("0"),
        )

        # Year 1: no gains, use $3k cap
        result_y1 = apply_carryforward(cf, st_gains=Decimal("0"), lt_gains=Decimal("0"))
        assert result_y1.ordinary_income_offset == Decimal("3000")
        assert result_y1.remaining_carryforward.short_term == Decimal("7000")

        # Year 2: no gains, use $3k cap again
        result_y2 = apply_carryforward(
            result_y1.remaining_carryforward,
            st_gains=Decimal("0"),
            lt_gains=Decimal("0"),
        )
        assert result_y2.ordinary_income_offset == Decimal("3000")
        assert result_y2.remaining_carryforward.short_term == Decimal("4000")

        # Year 3: no gains, use $3k cap again
        result_y3 = apply_carryforward(
            result_y2.remaining_carryforward,
            st_gains=Decimal("0"),
            lt_gains=Decimal("0"),
        )
        assert result_y3.ordinary_income_offset == Decimal("3000")
        assert result_y3.remaining_carryforward.short_term == Decimal("1000")

    def test_carryforward_exhausted_by_future_gains(self):
        """Carryforward carried across years is consumed by future gains."""
        cf = LossCarryforward(
            short_term=Decimal("15000"),
            long_term=Decimal("5000"),
        )

        # Year 1: small gains
        result_y1 = apply_carryforward(
            cf, st_gains=Decimal("2000"), lt_gains=Decimal("1000")
        )
        # ST cf: 15000 - 2000 = 13000 remaining
        # LT cf: 5000 - 1000 = 4000 remaining
        # Total remaining after offsets: 17000, then $3k ordinary
        assert result_y1.taxable_gains_after == Decimal("0")
        assert result_y1.ordinary_income_offset == Decimal("3000")
        total_y1 = result_y1.remaining_carryforward.total
        assert total_y1 == Decimal("14000")

        # Year 2: large gains consume remaining carryforward
        result_y2 = apply_carryforward(
            result_y1.remaining_carryforward,
            st_gains=Decimal("20000"),
            lt_gains=Decimal("10000"),
        )
        # Carryforward should be fully consumed
        assert result_y2.remaining_carryforward.total == Decimal("0")
        assert result_y2.ordinary_income_offset == Decimal("0")
        # Taxable = 30000 - 14000 = 16000
        assert result_y2.taxable_gains_after == Decimal("16000")

    def test_cross_type_offset(self):
        """ST carryforward can offset LT gains and vice versa."""
        cf = LossCarryforward(
            short_term=Decimal("5000"),
            long_term=Decimal("0"),
        )
        # Only LT gains this year — ST carryforward crosses over
        result = apply_carryforward(
            cf, st_gains=Decimal("0"), lt_gains=Decimal("3000")
        )

        # ST cf offsets LT gains: 5000 - 3000 = 2000 remaining ST cf
        assert result.taxable_gains_after == Decimal("0")
        # Remaining 2000, cap at $2000 (less than $3000)
        assert result.ordinary_income_offset == Decimal("2000")
        assert result.remaining_carryforward.total == Decimal("0")


class TestUseNowVsCarry:
    """'Use now' vs 'carry forward' comparison works — acceptance criterion."""

    def test_use_now_better_at_high_current_rate(self):
        """When current rate is high and future rate is lower, use now wins."""
        result = model_use_now_vs_carry(
            available_loss=Decimal("10000"),
            current_gains=Decimal("10000"),
            current_st_rate=Decimal("0.37"),
            expected_future_rate=Decimal("0.20"),
            gains_are_short_term=True,
        )

        assert isinstance(result, UseNowVsCarryResult)
        # Use now: 10000 * 0.37 = $3,700
        assert result.use_now_benefit == Decimal("3700")
        # Carry: 10000 * 0.20 = $2,000
        assert result.carry_forward_benefit == Decimal("2000")
        assert result.recommendation == "use_now"

    def test_carry_better_when_future_rate_higher(self):
        """When expected future rate exceeds current applicable rate, carry wins."""
        result = model_use_now_vs_carry(
            available_loss=Decimal("10000"),
            current_gains=Decimal("10000"),
            current_st_rate=Decimal("0.20"),
            current_lt_rate=Decimal("0.15"),
            expected_future_rate=Decimal("0.37"),
            gains_are_short_term=False,
        )

        # Use now: 10000 * 0.15 (LT rate) = $1,500
        assert result.use_now_benefit == Decimal("1500")
        # Carry: 10000 * 0.37 = $3,700
        assert result.carry_forward_benefit == Decimal("3700")
        assert result.recommendation == "carry_forward"

    def test_excess_loss_uses_ordinary_cap(self):
        """Loss exceeding gains uses $3,000 ordinary income offset."""
        result = model_use_now_vs_carry(
            available_loss=Decimal("15000"),
            current_gains=Decimal("5000"),
            current_st_rate=Decimal("0.37"),
            expected_future_rate=Decimal("0.37"),
            gains_are_short_term=True,
        )

        # Use now: offset $5k gains at 37% = $1,850 + $3k ordinary at 37% = $1,110
        # Total use_now = $2,960
        assert result.use_now_benefit == Decimal("2960")
        # Carry: 15000 * 0.37 = $5,550
        assert result.carry_forward_benefit == Decimal("5550")
        assert result.recommendation == "carry_forward"

    def test_breakeven_rate_calculation(self):
        """Breakeven rate is where carry equals use_now benefit."""
        result = model_use_now_vs_carry(
            available_loss=Decimal("10000"),
            current_gains=Decimal("10000"),
            current_st_rate=Decimal("0.37"),
            expected_future_rate=Decimal("0.37"),
            gains_are_short_term=True,
        )

        # Breakeven = use_now_benefit / available_loss = 3700 / 10000 = 0.37
        assert result.breakeven_rate == Decimal("0.37")

    def test_zero_loss_no_error(self):
        """Zero available loss produces zero benefits."""
        result = model_use_now_vs_carry(
            available_loss=Decimal("0"),
            current_gains=Decimal("5000"),
        )

        assert result.use_now_benefit == Decimal("0")
        assert result.carry_forward_benefit == Decimal("0")
        assert result.breakeven_rate == Decimal("0")


class TestDecimalPrecision:
    """Decimal precision maintained — acceptance criterion."""

    def test_no_float_contamination_in_result(self):
        """All monetary fields must be Decimal, not float."""
        gains = [
            RealizedGain(
                proceeds=Decimal("10000.50"),
                cost_basis=Decimal("9000.25"),
                is_long_term=True,
            ),
        ]
        result = after_tax_return(
            gains=gains,
            beginning_value=Decimal("100000"),
            ending_value=Decimal("105000"),
        )

        assert isinstance(result.pre_tax_return, Decimal)
        assert isinstance(result.after_tax_return, Decimal)
        assert isinstance(result.tax_drag, Decimal)
        assert isinstance(result.st_taxes_paid, Decimal)
        assert isinstance(result.lt_taxes_paid, Decimal)

    def test_no_float_in_tax_alpha(self):
        """TaxAlphaResult fields are all Decimal."""
        result = tax_alpha_vs_fifo(
            optimal_gains=[
                RealizedGain(Decimal("11000"), Decimal("10000"), True)
            ],
            fifo_gains=[
                RealizedGain(Decimal("11000"), Decimal("10000"), False)
            ],
            portfolio_value=Decimal("100000"),
        )

        assert isinstance(result.optimal_tax, Decimal)
        assert isinstance(result.fifo_tax, Decimal)
        assert isinstance(result.tax_alpha, Decimal)
        assert isinstance(result.alpha_bps, Decimal)

    def test_no_float_in_carryforward(self):
        """Carryforward result fields are all Decimal."""
        cf = LossCarryforward(
            short_term=Decimal("5000.33"),
            long_term=Decimal("2500.67"),
        )
        result = apply_carryforward(cf, st_gains=Decimal("1000"), lt_gains=Decimal("500"))

        assert isinstance(result.taxable_gains_after, Decimal)
        assert isinstance(result.ordinary_income_offset, Decimal)
        assert isinstance(result.remaining_carryforward.short_term, Decimal)
        assert isinstance(result.remaining_carryforward.long_term, Decimal)

    def test_fractional_cents_preserved(self):
        """Sub-cent precision is maintained through calculations."""
        gains = [
            RealizedGain(
                proceeds=Decimal("10000.123456"),
                cost_basis=Decimal("9000.654321"),
                is_long_term=False,
            ),
        ]
        result = after_tax_return(
            gains=gains,
            beginning_value=Decimal("100000"),
            ending_value=Decimal("105000"),
        )

        # Gain = 10000.123456 - 9000.654321 = 999.469135
        # Tax = 999.469135 * 0.37 = 369.803539.95 (exact Decimal arithmetic)
        expected_gain = Decimal("10000.123456") - Decimal("9000.654321")
        expected_tax = expected_gain * Decimal("0.37")
        assert result.st_taxes_paid == expected_tax
