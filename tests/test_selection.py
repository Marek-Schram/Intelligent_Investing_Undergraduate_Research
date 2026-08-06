"""Tests for tax/selection.py: after-tax-optimal lot selection wired to harvesting.

TICKET-035/036. Hand-computed Decimal fixtures throughout -- exact cents, no golden files.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from durable.tax.harvest import AccountType, TaxLot, Transaction
from durable.tax.lots import TaxRates
from durable.tax.selection import (
    harvest_lot_to_lot,
    select_after_tax_optimal_harvest_lots,
    wash_sale_risk_for_ticker,
)


def _tax_rates() -> TaxRates:
    """22% federal ST + 5% state = 27% effective ST; 15% federal LT + 5% state = 20% LT."""
    return TaxRates(
        short_term_rate=Decimal("0.22"),
        long_term_rate=Decimal("0.15"),
        state_rate=Decimal("0.05"),
    )


class TestHarvestLotToLot:
    """Conversion from harvest.TaxLot (whole-lot) to lots.Lot (per-share)."""

    def test_basic_conversion(self):
        tax_lot = TaxLot(
            lot_id="LOT-1",
            ticker="AAPL",
            shares=Decimal("10.000000"),
            cost_basis=Decimal("1900.00"),
            purchase_date=date(2024, 1, 1),
            account_type=AccountType.TAXABLE,
            account_id="tax-001",
        )
        lot = harvest_lot_to_lot(tax_lot, sleeve="C")

        assert lot.lot_id == "LOT-1"
        assert lot.ticker == "AAPL"
        assert lot.sleeve == "C"
        assert lot.account == "taxable"
        assert lot.shares == Decimal("10.000000")
        assert lot.cost_basis_per_share == Decimal("190.000000")
        assert lot.adjusted_basis == Decimal("1900.00")
        assert lot.closed_at is None

    def test_rejects_non_positive_shares(self):
        tax_lot = TaxLot(
            lot_id="LOT-2",
            ticker="AAPL",
            shares=Decimal("0"),
            cost_basis=Decimal("0"),
            purchase_date=date(2024, 1, 1),
            account_type=AccountType.TAXABLE,
            account_id="tax-001",
        )
        with pytest.raises(ValueError, match="non-positive shares"):
            harvest_lot_to_lot(tax_lot)


class TestWashSaleRiskForTicker:
    def test_no_purchases_means_no_risk(self):
        risk = wash_sale_risk_for_ticker("AAPL", date(2025, 6, 15), [], AccountType.TAXABLE)
        assert risk is None

    def test_cross_account_purchase_produces_risk(self):
        roth_purchase = Transaction(
            ticker="AAPL",
            trade_date=date(2025, 6, 20),
            shares=Decimal("5"),
            price_per_share=Decimal("150.00"),
            account_type=AccountType.ROTH,
            account_id="roth-001",
            is_drip=False,
        )
        risk = wash_sale_risk_for_ticker(
            "AAPL", date(2025, 6, 15), [roth_purchase], AccountType.TAXABLE
        )
        assert risk is not None
        assert risk.at_risk is True
        assert "PERMANENTLY LOST" in risk.reason


class TestSelectAfterTaxOptimalHarvestLots:
    """Core integration test: end-to-end pipeline disagrees with naive HIFO and wins."""

    def test_tax_optimal_beats_hifo_when_hifo_pick_is_wash_sale_disallowed(self):
        """Hand-computed, mirrors tests/test_lots.py::TestTaxOptimalBeatsHIFO (the proven
        lots.py-level scenario) but driven end-to-end through the harvest.TaxLot ->
        selection.py -> lots.Lot pipeline, using `wash_sale_risk_overrides` for the
        lot-specific case where a broker's actual replacement-share matching (IRS Pub.
        550) taints LOT-I's loss but not LOT-J's -- information finer-grained than the
        automatic ticker-wide scan (tested separately below) can produce on its own.

        - LOT-I: 10 sh, basis $250/sh, short-term. Loss $50/sh, but wash-sale disallowed
          -> after-tax proceeds/sh = $200.00 (no benefit, no cost).
        - LOT-J: 10 sh, basis $220/sh, long-term. Loss $20/sh, allowed -> tax benefit/sh
          = $20 * 0.20 (LT rate) = $4.00 -> after-tax proceeds/sh = $204.00.

        HIFO picks the highest basis (LOT-I, $250 > $220) -- exactly the wash-sale trap.
        TAX_OPTIMAL picks LOT-J, netting $40 more across 10 shares ($2,040 vs $2,000).
        """
        sale_date = date(2025, 6, 15)
        tax_rates = _tax_rates()

        lot_i = TaxLot(
            lot_id="LOT-I",
            ticker="XYZ",
            shares=Decimal("10.000000"),
            cost_basis=Decimal("2500.00"),  # $250/sh
            purchase_date=date(2025, 4, 15),  # short-term
            account_type=AccountType.TAXABLE,
            account_id="tax-001",
        )
        lot_j = TaxLot(
            lot_id="LOT-J",
            ticker="XYZ",
            shares=Decimal("10.000000"),
            cost_basis=Decimal("2200.00"),  # $220/sh
            purchase_date=date(2024, 4, 1),  # long-term (>366 days before sale_date)
            account_type=AccountType.TAXABLE,
            account_id="tax-001",
        )
        current_price = Decimal("200.00")

        from durable.tax.lots import WashSaleRisk

        overrides = {
            "LOT-I": WashSaleRisk(
                at_risk=True,
                conflicting_lot_id="LOT-ROTH-99",
                reason="Cross-account Roth purchase within 30 days",
            ),
        }

        comparison = select_after_tax_optimal_harvest_lots(
            ticker="XYZ",
            taxable_lots=[lot_i, lot_j],
            current_price=current_price,
            sale_date=sale_date,
            tax_rates=tax_rates,
            all_transactions=[],  # override supplies the risk directly
            shares_to_sell=Decimal("10.000000"),
            wash_sale_risk_overrides=overrides,
        )

        # HIFO picks LOT-I (highest basis: $250 > $220) -- exactly the wash-sale trap.
        assert comparison.naive_hifo[0].lot.lot_id == "LOT-I"
        assert comparison.after_tax_proceeds_hifo == Decimal("2000.00")

        # TAX_OPTIMAL avoids the wash-sale-tainted lot and sells LOT-J instead.
        assert comparison.tax_optimal[0].lot.lot_id == "LOT-J"
        assert comparison.after_tax_proceeds_optimal == Decimal("2040.00")

        assert comparison.tax_alpha_vs_hifo == Decimal("40.00")
        assert comparison.tax_alpha_vs_hifo > Decimal("0")
        assert comparison.wash_sale_risks.get("LOT-I") is not None
        assert comparison.wash_sale_risks["LOT-I"].at_risk is True
        assert "LOT-J" in comparison.explanation
        assert "TAX_OPTIMAL" in comparison.explanation

    def test_automatic_scan_flags_every_lot_of_the_ticker_conservatively(self):
        """Without an override, the automatic scan (harvest.scan_all_accounts) applies
        the SAME risk to every lot of the ticker -- the conservative default described
        in the docstring. Two loss lots of the same ticker both end up wash-sale-tainted
        even though only one of them is economically "the" lot that got repurchased."""
        sale_date = date(2025, 6, 15)
        tax_rates = _tax_rates()

        lot_a = TaxLot(
            lot_id="LOT-A",
            ticker="QRS",
            shares=Decimal("5.000000"),
            cost_basis=Decimal("1100.00"),  # $220/sh
            purchase_date=date(2024, 1, 1),
            account_type=AccountType.TAXABLE,
            account_id="tax-001",
        )
        lot_b = TaxLot(
            lot_id="LOT-B",
            ticker="QRS",
            shares=Decimal("5.000000"),
            cost_basis=Decimal("1050.00"),  # $210/sh
            purchase_date=date(2024, 6, 1),
            account_type=AccountType.TAXABLE,
            account_id="tax-001",
        )
        ira_purchase = Transaction(
            ticker="QRS",
            trade_date=date(2025, 6, 10),  # 5 days before sale: inside the window
            shares=Decimal("5"),
            price_per_share=Decimal("195.00"),
            account_type=AccountType.TRADITIONAL_IRA,
            account_id="ira-001",
            is_drip=False,
        )
        current_price = Decimal("200.00")

        comparison = select_after_tax_optimal_harvest_lots(
            ticker="QRS",
            taxable_lots=[lot_a, lot_b],
            current_price=current_price,
            sale_date=sale_date,
            tax_rates=tax_rates,
            all_transactions=[ira_purchase],
        )

        assert set(comparison.wash_sale_risks) == {"LOT-A", "LOT-B"}
        for risk in comparison.wash_sale_risks.values():
            assert risk.at_risk is True
            assert "PERMANENTLY LOST" in risk.reason

    def test_tax_optimal_beats_naive_fifo_via_holding_period(self):
        """FIFO always sells the chronologically OLDEST lot, regardless of tax cost. Here
        the oldest lot (bought 2022, long-term) sits on a big gain, while a lot bought
        just months ago (short-term) sits on a small loss. FIFO is forced into the gain;
        TAX_OPTIMAL correctly prefers realizing the loss instead."""
        sale_date = date(2025, 6, 15)
        tax_rates = _tax_rates()

        # Oldest lot by acquired_at (2022) -- FIFO must pick this one first. Long-term as
        # of the sale date, and sitting on a large gain.
        lot_old = TaxLot(
            lot_id="LOT-OLD",
            ticker="ABC",
            shares=Decimal("5.000000"),
            cost_basis=Decimal("500.00"),  # $100/sh
            purchase_date=date(2022, 1, 1),  # oldest; long-term as of the sale date
            account_type=AccountType.TAXABLE,
            account_id="tax-001",
        )
        # Bought recently (2025) -- short-term as of the sale date, and sitting on a loss.
        lot_new = TaxLot(
            lot_id="LOT-NEW",
            ticker="ABC",
            shares=Decimal("5.000000"),
            cost_basis=Decimal("1100.00"),  # $220/sh
            purchase_date=date(2025, 1, 1),  # newest; short-term as of the sale date
            account_type=AccountType.TAXABLE,
            account_id="tax-001",
        )
        current_price = Decimal("200.00")

        comparison = select_after_tax_optimal_harvest_lots(
            ticker="ABC",
            taxable_lots=[lot_old, lot_new],
            current_price=current_price,
            sale_date=sale_date,
            tax_rates=tax_rates,
            all_transactions=[],
            shares_to_sell=Decimal("5.000000"),
        )

        # FIFO sells the OLDEST lot: LOT-OLD, a $100/sh gain taxed at the LT rate.
        assert comparison.naive_fifo[0].lot.lot_id == "LOT-OLD"
        # gain/sh = $100, tax/sh = $100 * 0.20 (15% + 5% state, LT) = $20, proceeds/sh = $180.
        # 5 sh -> $900.00
        assert comparison.after_tax_proceeds_fifo == Decimal("900.00")

        # TAX_OPTIMAL sells LOT-NEW instead: a $20/sh LOSS, benefited at the ST rate.
        # loss/sh = -$20, benefit/sh = $20 * 0.27 = $5.40, proceeds/sh = $205.40.
        # 5 sh -> $1,027.00
        assert comparison.tax_optimal[0].lot.lot_id == "LOT-NEW"
        assert comparison.after_tax_proceeds_optimal == Decimal("1027.00")

        assert comparison.tax_alpha_vs_fifo == Decimal("127.00")
        assert comparison.tax_alpha_vs_fifo > Decimal("0")

    def test_specific_lot_ids_and_share_counts_are_named(self):
        """Rule 9: the comparison must name the SPECIFIC lot_ids and share counts sold."""
        sale_date = date(2025, 6, 15)
        tax_rates = _tax_rates()
        lot = TaxLot(
            lot_id="LOT-SOLO",
            ticker="SOLO",
            shares=Decimal("3.500000"),
            cost_basis=Decimal("700.00"),
            purchase_date=date(2024, 1, 1),
            account_type=AccountType.TAXABLE,
            account_id="tax-001",
        )
        comparison = select_after_tax_optimal_harvest_lots(
            ticker="SOLO",
            taxable_lots=[lot],
            current_price=Decimal("150.00"),
            sale_date=sale_date,
            tax_rates=tax_rates,
            all_transactions=[],
        )
        assert len(comparison.tax_optimal) == 1
        assert comparison.tax_optimal[0].lot.lot_id == "LOT-SOLO"
        assert comparison.tax_optimal[0].shares_to_sell == Decimal("3.500000")
        assert "LOT-SOLO" in comparison.explanation
        assert "TAX_OPTIMAL" in comparison.explanation

    def test_rejects_mismatched_ticker(self):
        sale_date = date(2025, 6, 15)
        lot = TaxLot(
            lot_id="LOT-X",
            ticker="AAPL",
            shares=Decimal("1"),
            cost_basis=Decimal("100"),
            purchase_date=date(2024, 1, 1),
            account_type=AccountType.TAXABLE,
            account_id="tax-001",
        )
        with pytest.raises(ValueError, match="must be for"):
            select_after_tax_optimal_harvest_lots(
                ticker="MSFT",
                taxable_lots=[lot],
                current_price=Decimal("150.00"),
                sale_date=sale_date,
                tax_rates=_tax_rates(),
                all_transactions=[],
            )

    def test_rejects_shares_to_sell_exceeding_available(self):
        sale_date = date(2025, 6, 15)
        lot = TaxLot(
            lot_id="LOT-Y",
            ticker="AAPL",
            shares=Decimal("1.000000"),
            cost_basis=Decimal("100.00"),
            purchase_date=date(2024, 1, 1),
            account_type=AccountType.TAXABLE,
            account_id="tax-001",
        )
        with pytest.raises(ValueError, match="only"):
            select_after_tax_optimal_harvest_lots(
                ticker="AAPL",
                taxable_lots=[lot],
                current_price=Decimal("150.00"),
                sale_date=sale_date,
                tax_rates=_tax_rates(),
                all_transactions=[],
                shares_to_sell=Decimal("5.000000"),
            )

    def test_rejects_float_shares_to_sell(self):
        sale_date = date(2025, 6, 15)
        lot = TaxLot(
            lot_id="LOT-Z",
            ticker="AAPL",
            shares=Decimal("1.000000"),
            cost_basis=Decimal("100.00"),
            purchase_date=date(2024, 1, 1),
            account_type=AccountType.TAXABLE,
            account_id="tax-001",
        )
        with pytest.raises(TypeError, match="must be Decimal"):
            select_after_tax_optimal_harvest_lots(
                ticker="AAPL",
                taxable_lots=[lot],
                current_price=Decimal("150.00"),
                sale_date=sale_date,
                tax_rates=_tax_rates(),
                all_transactions=[],
                shares_to_sell=0.5,  # type: ignore[arg-type]
            )
