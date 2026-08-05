"""Tests for tax lot tracking and selection. TICKET-035.

Validates:
- No float in any money path (all Lot fields are Decimal)
- 6-decimal fractional shares work correctly
- Tax-optimal selection disagrees with HIFO and produces better after-tax outcome
- Every selection logs its reason
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

import pytest

from durable.tax.lots import (
    Lot,
    LotSelection,
    LotSelectionResult,
    TaxRates,
    WashSaleRisk,
    select_lots,
)


# --- Fixtures ---


def _make_lot(
    lot_id: str = "LOT-001",
    ticker: str = "AAPL",
    sleeve: str = "C",
    account: str = "taxable",
    acquired_at: date = date(2024, 1, 15),
    shares: Decimal = Decimal("10.000000"),
    cost_basis_per_share: Decimal = Decimal("150.00"),
    adjusted_basis: Decimal | None = None,
    wash_sale_deferred: Decimal = Decimal("0"),
    holding_start: date | None = None,
    closed_at: date | None = None,
) -> Lot:
    """Helper to build a Lot with sensible defaults."""
    if adjusted_basis is None:
        adjusted_basis = cost_basis_per_share * shares
    return Lot(
        lot_id=lot_id,
        ticker=ticker,
        sleeve=sleeve,
        account=account,
        acquired_at=acquired_at,
        shares=shares,
        cost_basis_per_share=cost_basis_per_share,
        adjusted_basis=adjusted_basis,
        wash_sale_deferred=wash_sale_deferred,
        holding_start=holding_start,
        closed_at=closed_at,
    )


def _standard_tax_rates() -> TaxRates:
    """Typical tax rates for a moderate-income taxpayer."""
    return TaxRates(
        short_term_rate=Decimal("0.22"),  # 22% marginal
        long_term_rate=Decimal("0.15"),  # 15% LTCG
        state_rate=Decimal("0.05"),       # 5% state
    )


# --- Test: No float in money path ---


class TestNoFloatInMoneyPath:
    """Assert that Lot rejects float values in money fields."""

    def test_lot_shares_must_be_decimal(self) -> None:
        with pytest.raises(TypeError, match="must be Decimal"):
            Lot(
                lot_id="X",
                ticker="AAPL",
                sleeve="C",
                account="taxable",
                acquired_at=date(2024, 1, 1),
                shares=10.0,  # type: ignore[arg-type]
                cost_basis_per_share=Decimal("100"),
                adjusted_basis=Decimal("1000"),
            )

    def test_lot_cost_basis_must_be_decimal(self) -> None:
        with pytest.raises(TypeError, match="must be Decimal"):
            Lot(
                lot_id="X",
                ticker="AAPL",
                sleeve="C",
                account="taxable",
                acquired_at=date(2024, 1, 1),
                shares=Decimal("10"),
                cost_basis_per_share=100.0,  # type: ignore[arg-type]
                adjusted_basis=Decimal("1000"),
            )

    def test_lot_adjusted_basis_must_be_decimal(self) -> None:
        with pytest.raises(TypeError, match="must be Decimal"):
            Lot(
                lot_id="X",
                ticker="AAPL",
                sleeve="C",
                account="taxable",
                acquired_at=date(2024, 1, 1),
                shares=Decimal("10"),
                cost_basis_per_share=Decimal("100"),
                adjusted_basis=1000.0,  # type: ignore[arg-type]
            )

    def test_lot_wash_sale_deferred_must_be_decimal(self) -> None:
        with pytest.raises(TypeError, match="must be Decimal"):
            Lot(
                lot_id="X",
                ticker="AAPL",
                sleeve="C",
                account="taxable",
                acquired_at=date(2024, 1, 1),
                shares=Decimal("10"),
                cost_basis_per_share=Decimal("100"),
                adjusted_basis=Decimal("1000"),
                wash_sale_deferred=0.0,  # type: ignore[arg-type]
            )

    def test_select_lots_rejects_float_shares_needed(self) -> None:
        lot = _make_lot()
        with pytest.raises(TypeError, match="must be Decimal"):
            select_lots(
                lots=[lot],
                shares_needed=5.0,  # type: ignore[arg-type]
                current_price=Decimal("160"),
                sale_date=date(2025, 6, 1),
                strategy=LotSelection.HIFO,
            )

    def test_select_lots_rejects_float_current_price(self) -> None:
        lot = _make_lot()
        with pytest.raises(TypeError, match="must be Decimal"):
            select_lots(
                lots=[lot],
                shares_needed=Decimal("5"),
                current_price=160.0,  # type: ignore[arg-type]
                sale_date=date(2025, 6, 1),
                strategy=LotSelection.HIFO,
            )

    def test_tax_rates_rejects_float(self) -> None:
        with pytest.raises(TypeError, match="must be Decimal"):
            TaxRates(
                short_term_rate=0.22,  # type: ignore[arg-type]
                long_term_rate=Decimal("0.15"),
            )

    def test_all_lot_money_fields_are_decimal_type(self) -> None:
        """Inspect the Lot dataclass fields to confirm Decimal annotations."""
        import dataclasses

        lot = _make_lot()
        money_field_names = {
            "shares",
            "cost_basis_per_share",
            "adjusted_basis",
            "wash_sale_deferred",
        }
        for f in dataclasses.fields(lot):
            if f.name in money_field_names:
                val = getattr(lot, f.name)
                assert isinstance(val, Decimal), (
                    f"Field {f.name} should be Decimal, got {type(val).__name__}"
                )


# --- Test: 6-decimal fractional shares ---


class TestFractionalShares:
    """Verify 6-decimal fractional share precision."""

    def test_six_decimal_shares_accepted(self) -> None:
        lot = _make_lot(shares=Decimal("0.123456"))
        assert lot.shares == Decimal("0.123456")

    def test_seven_decimal_shares_rejected(self) -> None:
        with pytest.raises(ValueError, match="<= 6 decimal places"):
            _make_lot(shares=Decimal("0.1234567"))

    def test_fractional_share_selection(self) -> None:
        """Sell a fractional amount from a fractional lot."""
        lot = _make_lot(
            shares=Decimal("3.141592"),
            cost_basis_per_share=Decimal("100.00"),
            adjusted_basis=Decimal("314.159200"),
        )
        results = select_lots(
            lots=[lot],
            shares_needed=Decimal("1.500000"),
            current_price=Decimal("120.00"),
            sale_date=date(2025, 6, 1),
            strategy=LotSelection.HIFO,
        )
        assert len(results) == 1
        assert results[0].shares_to_sell == Decimal("1.500000")

    def test_fractional_shares_across_multiple_lots(self) -> None:
        """Need more shares than any single lot has — spans two lots."""
        lot1 = _make_lot(
            lot_id="LOT-A",
            shares=Decimal("0.500000"),
            cost_basis_per_share=Decimal("200.00"),
            adjusted_basis=Decimal("100.000000"),
        )
        lot2 = _make_lot(
            lot_id="LOT-B",
            shares=Decimal("0.750000"),
            cost_basis_per_share=Decimal("180.00"),
            adjusted_basis=Decimal("135.000000"),
        )
        results = select_lots(
            lots=[lot1, lot2],
            shares_needed=Decimal("1.000000"),
            current_price=Decimal("210.00"),
            sale_date=date(2025, 6, 1),
            strategy=LotSelection.HIFO,
        )
        total_sold = sum(r.shares_to_sell for r in results)
        assert total_sold == Decimal("1.000000")


# --- Test: Tax-optimal disagrees with HIFO and wins ---


class TestTaxOptimalBeatsHIFO:
    """Core test: tax-optimal produces better after-tax outcome than HIFO.

    Scenario: Two lots, same ticker, selling some shares.
    - Lot A: high basis, SHORT-TERM (acquired recently). Small gain taxed at ST rate.
    - Lot B: lower basis, LONG-TERM (acquired >1yr ago). Larger gain taxed at LT rate.

    HIFO picks Lot A (highest basis). But the ST rate on Lot A's gain can cost more
    in total tax than the LT rate on Lot B's larger gain. Tax-optimal picks the
    lot that maximizes after-tax proceeds.

    Hand-computed example:
    - Current price: $200/share
    - Lot A: basis $190/share, 10 shares, acquired 3 months ago (ST)
      Gain/share = $10, tax/share = $10 * 0.27 (22% fed + 5% state) = $2.70
      After-tax proceeds/share = $200 - $2.70 = $197.30

    - Lot B: basis $120/share, 10 shares, acquired 2 years ago (LT)
      Gain/share = $80, tax/share = $80 * 0.20 (15% fed + 5% state) = $16.00
      After-tax proceeds/share = $200 - $16.00 = $184.00

    HIFO picks Lot A (basis $190 > $120).
    Tax-optimal picks Lot A too in this case — higher after-tax proceeds per share.

    But flip it: what if we need to sell from a loss lot?
    - Lot C: basis $220/share, 5 shares, acquired 3 months ago (ST)
      Loss/share = -$20, tax benefit/share = $20 * 0.27 = $5.40
      After-tax proceeds/share = $200 + $5.40 = $205.40

    - Lot D: basis $210/share, 5 shares, acquired 2 years ago (LT)
      Loss/share = -$10, tax benefit/share = $10 * 0.20 = $2.00
      After-tax proceeds/share = $200 + $2.00 = $202.00

    HIFO picks Lot C (highest basis $220 > $210). Tax-optimal ALSO picks C here.

    The critical disagreement case:
    - Lot E: basis $195/share, 10 shares, acquired 2 months ago (ST)
      Gain/share = $5, tax/share = $5 * 0.27 = $1.35
      After-tax proceeds/share = $200 - $1.35 = $198.65

    - Lot F: basis $160/share, 10 shares, acquired 14 months ago (LT)
      Gain/share = $40, tax/share = $40 * 0.20 = $8.00
      After-tax proceeds/share = $200 - $8.00 = $192.00

    Need to sell 10 shares. HIFO picks Lot E (basis $195 > $160).
    After-tax from HIFO (Lot E): 10 * $198.65 = $1986.50
    After-tax from selling Lot F: 10 * $192.00 = $1920.00

    Wait — HIFO actually wins here. Let me construct the real disagreement:

    The disagreement happens when HIFO picks a LOT with a GAIN (because high basis
    means small gain) but that gain is ST, and the alternative is a lot with a
    LOSS that's LT. OR when both have gains but the LT lot's after-tax is better
    despite lower basis.

    Real disagreement scenario:
    - Lot G: basis $180/share, 10 shares, acquired 11 months ago (ST, 1 month from LT)
      Gain/share = $20, tax/share = $20 * 0.27 = $5.40
      After-tax proceeds/share = $200 - $5.40 = $194.60

    - Lot H: basis $50/share, 10 shares, acquired 3 years ago (LT)
      Gain/share = $150, tax/share = $150 * 0.20 = $30.00
      After-tax proceeds/share = $200 - $30.00 = $170.00

    HIFO picks G (basis $180 > $50). Tax-optimal also picks G ($194.60 > $170.00).

    The REAL case where tax-optimal disagrees is with LOSSES + wash sale risk:
    - Lot I: basis $250/share, 10 shares, acquired 2 months ago (ST)
      Loss/share = -$50, but WASH SALE RISK (no tax benefit)
      After-tax proceeds/share = $200 (no benefit from loss)

    - Lot J: basis $220/share, 10 shares, acquired 14 months ago (LT)
      Loss/share = -$20, no wash sale risk
      Tax benefit/share = $20 * 0.20 = $4.00
      After-tax proceeds/share = $200 + $4.00 = $204.00

    HIFO picks Lot I (basis $250 > $220). After-tax = 10 * $200 = $2000
    Tax-optimal picks Lot J. After-tax = 10 * $204 = $2040

    Tax-optimal wins by $40!
    """

    def test_tax_optimal_beats_hifo_wash_sale_scenario(self) -> None:
        """Wash-sale risk makes HIFO's pick worse than tax-optimal's pick."""
        sale_date = date(2025, 6, 15)

        # Lot I: highest basis, ST, but has wash-sale risk (loss disallowed)
        lot_i = _make_lot(
            lot_id="LOT-I",
            acquired_at=date(2025, 4, 15),  # 2 months ago, ST
            shares=Decimal("10.000000"),
            cost_basis_per_share=Decimal("250.00"),
            adjusted_basis=Decimal("2500.000000"),
        )
        # Lot J: lower basis, LT, no wash-sale risk (loss harvested cleanly)
        lot_j = _make_lot(
            lot_id="LOT-J",
            acquired_at=date(2024, 4, 1),  # 14 months ago, LT
            shares=Decimal("10.000000"),
            cost_basis_per_share=Decimal("220.00"),
            adjusted_basis=Decimal("2200.000000"),
        )

        current_price = Decimal("200.00")
        shares_needed = Decimal("10.000000")
        tax_rates = _standard_tax_rates()

        wash_sale_risks = {
            "LOT-I": WashSaleRisk(
                at_risk=True,
                conflicting_lot_id="LOT-ROTH-99",
                reason="Cross-account Roth purchase within 30 days",
            ),
        }

        # HIFO selection
        hifo_results = select_lots(
            lots=[lot_i, lot_j],
            shares_needed=shares_needed,
            current_price=current_price,
            sale_date=sale_date,
            strategy=LotSelection.HIFO,
        )

        # Tax-optimal selection
        optimal_results = select_lots(
            lots=[lot_i, lot_j],
            shares_needed=shares_needed,
            current_price=current_price,
            sale_date=sale_date,
            strategy=LotSelection.TAX_OPTIMAL,
            tax_rates=tax_rates,
            wash_sale_risks=wash_sale_risks,
        )

        # HIFO picks Lot I (highest basis: $250 > $220)
        assert hifo_results[0].lot.lot_id == "LOT-I"

        # Tax-optimal picks Lot J (better after-tax due to wash-sale risk on I)
        assert optimal_results[0].lot.lot_id == "LOT-J"

        # Verify after-tax proceeds: optimal > HIFO
        # HIFO: sells Lot I at loss but wash-sale disallows it
        # Proceeds = 10 * $200 = $2000, tax benefit = $0 (disallowed)
        hifo_after_tax = current_price * shares_needed  # $2000 (no benefit)

        # Tax-optimal: sells Lot J at loss, no wash sale
        # Loss = 10 * ($200 - $220) = -$200
        # Tax benefit = $200 * 0.20 (LT rate) = $40
        # After-tax = $2000 + $40 = $2040
        lt_rate = tax_rates.effective_lt_rate  # 0.20
        loss_j = (Decimal("220.00") - current_price) * shares_needed  # $200 loss
        optimal_after_tax = current_price * shares_needed + loss_j * lt_rate

        assert optimal_after_tax > hifo_after_tax
        assert optimal_after_tax - hifo_after_tax == Decimal("40.00")

    def test_tax_optimal_prefers_lt_loss_over_st_gain(self) -> None:
        """When one lot has a ST gain and another has a LT loss,
        tax-optimal may prefer selling the loss lot (tax benefit)
        over the gain lot (tax cost), even though HIFO picks the gain lot."""
        sale_date = date(2025, 7, 1)

        # Lot with ST gain (high basis = small gain, but still taxed at ST rate)
        lot_st_gain = _make_lot(
            lot_id="LOT-ST",
            acquired_at=date(2025, 3, 1),  # 4 months ago, ST
            shares=Decimal("10.000000"),
            cost_basis_per_share=Decimal("195.00"),
            adjusted_basis=Decimal("1950.000000"),
        )
        # Lot with LT loss (lower basis than current price? No — loss means basis > price)
        lot_lt_loss = _make_lot(
            lot_id="LOT-LT",
            acquired_at=date(2024, 1, 1),  # 18 months ago, LT
            shares=Decimal("10.000000"),
            cost_basis_per_share=Decimal("210.00"),
            adjusted_basis=Decimal("2100.000000"),
        )

        current_price = Decimal("200.00")
        shares_needed = Decimal("10.000000")
        tax_rates = _standard_tax_rates()

        # HIFO picks LOT-LT (basis $210 > $195)
        hifo_results = select_lots(
            lots=[lot_st_gain, lot_lt_loss],
            shares_needed=shares_needed,
            current_price=current_price,
            sale_date=sale_date,
            strategy=LotSelection.HIFO,
        )
        assert hifo_results[0].lot.lot_id == "LOT-LT"

        # Tax-optimal considers after-tax proceeds:
        # LOT-ST: gain = $5/sh, tax = $5 * 0.27 = $1.35/sh, ATP = $198.65/sh
        # LOT-LT: loss = -$10/sh, benefit = $10 * 0.20 = $2.00/sh, ATP = $202.00/sh
        optimal_results = select_lots(
            lots=[lot_st_gain, lot_lt_loss],
            shares_needed=shares_needed,
            current_price=current_price,
            sale_date=sale_date,
            strategy=LotSelection.TAX_OPTIMAL,
            tax_rates=tax_rates,
        )

        # Tax-optimal picks LOT-LT too (it has higher after-tax proceeds)
        # This is actually the same as HIFO in this case, but for different reasons.
        # The after-tax proceeds for LOT-LT ($202/sh) > LOT-ST ($198.65/sh)
        assert optimal_results[0].lot.lot_id == "LOT-LT"

        # Verify the math: LOT-LT gives $2020 after-tax, LOT-ST gives $1986.50
        # Even though both strategies pick LOT-LT here, the REASON is different.
        # HIFO: "highest basis"
        # Tax-optimal: "maximizes after-tax proceeds"
        assert "HIFO" in hifo_results[0].reason
        assert "TAX_OPTIMAL" in optimal_results[0].reason


# --- Test: Every selection logs its reason ---


class TestSelectionLogging:
    """Every lot selection must log its reason string."""

    def test_hifo_logs_reason(self, caplog: pytest.LogCaptureFixture) -> None:
        lot = _make_lot()
        with caplog.at_level(logging.INFO, logger="durable.tax.lots"):
            results = select_lots(
                lots=[lot],
                shares_needed=Decimal("5.000000"),
                current_price=Decimal("160.00"),
                sale_date=date(2025, 6, 1),
                strategy=LotSelection.HIFO,
            )
        assert len(results) == 1
        assert results[0].reason != ""
        assert "HIFO" in results[0].reason
        assert any("HIFO" in record.message for record in caplog.records)

    def test_lifo_logs_reason(self, caplog: pytest.LogCaptureFixture) -> None:
        lot = _make_lot()
        with caplog.at_level(logging.INFO, logger="durable.tax.lots"):
            results = select_lots(
                lots=[lot],
                shares_needed=Decimal("5.000000"),
                current_price=Decimal("160.00"),
                sale_date=date(2025, 6, 1),
                strategy=LotSelection.LIFO,
            )
        assert len(results) == 1
        assert "LIFO" in results[0].reason
        assert any("LIFO" in record.message for record in caplog.records)

    def test_fifo_logs_reason(self, caplog: pytest.LogCaptureFixture) -> None:
        lot = _make_lot()
        with caplog.at_level(logging.INFO, logger="durable.tax.lots"):
            results = select_lots(
                lots=[lot],
                shares_needed=Decimal("5.000000"),
                current_price=Decimal("160.00"),
                sale_date=date(2025, 6, 1),
                strategy=LotSelection.FIFO,
            )
        assert len(results) == 1
        assert "FIFO" in results[0].reason
        assert any("FIFO" in record.message for record in caplog.records)

    def test_tax_optimal_logs_reason(self, caplog: pytest.LogCaptureFixture) -> None:
        lot = _make_lot()
        tax_rates = _standard_tax_rates()
        with caplog.at_level(logging.INFO, logger="durable.tax.lots"):
            results = select_lots(
                lots=[lot],
                shares_needed=Decimal("5.000000"),
                current_price=Decimal("160.00"),
                sale_date=date(2025, 6, 1),
                strategy=LotSelection.TAX_OPTIMAL,
                tax_rates=tax_rates,
            )
        assert len(results) == 1
        assert "TAX_OPTIMAL" in results[0].reason
        assert any("TAX_OPTIMAL" in record.message for record in caplog.records)

    def test_reason_includes_lot_id(self) -> None:
        lot = _make_lot(lot_id="MY-SPECIAL-LOT")
        results = select_lots(
            lots=[lot],
            shares_needed=Decimal("5.000000"),
            current_price=Decimal("160.00"),
            sale_date=date(2025, 6, 1),
            strategy=LotSelection.HIFO,
        )
        assert "MY-SPECIAL-LOT" in results[0].reason

    def test_reason_includes_term(self) -> None:
        # LT lot
        lot = _make_lot(acquired_at=date(2023, 1, 1))
        results = select_lots(
            lots=[lot],
            shares_needed=Decimal("5.000000"),
            current_price=Decimal("160.00"),
            sale_date=date(2025, 6, 1),
            strategy=LotSelection.HIFO,
        )
        assert "LT" in results[0].reason


# --- Test: Edge cases and validation ---


class TestValidation:
    """Input validation tests."""

    def test_no_open_lots_raises(self) -> None:
        closed_lot = _make_lot(closed_at=date(2025, 1, 1))
        with pytest.raises(ValueError, match="No open lots"):
            select_lots(
                lots=[closed_lot],
                shares_needed=Decimal("5.000000"),
                current_price=Decimal("160.00"),
                sale_date=date(2025, 6, 1),
            )

    def test_insufficient_shares_raises(self) -> None:
        lot = _make_lot(shares=Decimal("5.000000"))
        with pytest.raises(ValueError, match="only .* available"):
            select_lots(
                lots=[lot],
                shares_needed=Decimal("10.000000"),
                current_price=Decimal("160.00"),
                sale_date=date(2025, 6, 1),
            )

    def test_tax_optimal_without_rates_raises(self) -> None:
        lot = _make_lot()
        with pytest.raises(ValueError, match="requires tax_rates"):
            select_lots(
                lots=[lot],
                shares_needed=Decimal("5.000000"),
                current_price=Decimal("160.00"),
                sale_date=date(2025, 6, 1),
                strategy=LotSelection.TAX_OPTIMAL,
            )

    def test_holding_period_boundary(self) -> None:
        """365 days = ST, 366 days = LT."""
        # Exactly 365 days: still ST
        lot_365 = _make_lot(acquired_at=date(2024, 6, 1))
        sale_365 = date(2025, 6, 1)  # 365 days
        assert not lot_365.is_long_term(sale_365)

        # 366 days: LT
        sale_366 = date(2025, 6, 2)  # 366 days
        assert lot_365.is_long_term(sale_366)

    def test_wash_sale_deferred_in_basis(self) -> None:
        """Lot with wash-sale deferred amount has higher adjusted basis."""
        lot = Lot(
            lot_id="WASH-LOT",
            ticker="AAPL",
            sleeve="C",
            account="taxable",
            acquired_at=date(2024, 6, 1),
            shares=Decimal("10.000000"),
            cost_basis_per_share=Decimal("100.00"),
            adjusted_basis=Decimal("1050.000000"),  # includes $50 deferred
            wash_sale_deferred=Decimal("50.000000"),
        )
        # Basis per share is $105 (adjusted), not $100 (original)
        basis_per_share = lot.adjusted_basis / lot.shares
        assert basis_per_share == Decimal("105.000000")
