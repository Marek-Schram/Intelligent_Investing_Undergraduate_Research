"""Tax loss harvesting and wash sale tests. TICKET-036. docs/11 section 3."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from durable.tax.harvest import (
    GICS_SECTOR_TO_ETF,
    AccountType,
    LossType,
    TaxLot,
    Transaction,
    WashSaleWindow,
    adjust_basis_for_wash_sale,
    harvest_opportunity,
    refuse_if_wanted,
    replacement_etf,
    scan_all_accounts,
    scan_all_accounts_with_loss,
)


class TestWashSaleWindow:
    """61-day window: 30 before + sale day + 30 after."""

    def test_window_is_61_days(self):
        """The wash sale window must be exactly 61 days (30+1+30)."""
        sale_date = date(2025, 6, 15)
        window = WashSaleWindow(sale_date)
        assert window.total_days == 61

    def test_window_start_is_30_days_before(self):
        sale_date = date(2025, 6, 15)
        window = WashSaleWindow(sale_date)
        assert window.start == date(2025, 5, 16)

    def test_window_end_is_30_days_after(self):
        sale_date = date(2025, 6, 15)
        window = WashSaleWindow(sale_date)
        assert window.end == date(2025, 7, 15)

    def test_window_contains_sale_date(self):
        sale_date = date(2025, 6, 15)
        window = WashSaleWindow(sale_date)
        assert window.contains(sale_date)

    def test_window_contains_boundary_start(self):
        sale_date = date(2025, 6, 15)
        window = WashSaleWindow(sale_date)
        assert window.contains(window.start)

    def test_window_contains_boundary_end(self):
        sale_date = date(2025, 6, 15)
        window = WashSaleWindow(sale_date)
        assert window.contains(window.end)

    def test_window_excludes_day_before_start(self):
        sale_date = date(2025, 6, 15)
        window = WashSaleWindow(sale_date)
        assert not window.contains(window.start - timedelta(days=1))

    def test_window_excludes_day_after_end(self):
        sale_date = date(2025, 6, 15)
        window = WashSaleWindow(sale_date)
        assert not window.contains(window.end + timedelta(days=1))


class TestCrossAccountWashSale:
    """Taxable-sale + Roth-purchase detected as wash sale, reported as PERMANENT loss."""

    def test_taxable_sale_roth_purchase_is_permanent(self):
        """A purchase in a Roth account within the window of a taxable sale
        permanently destroys the loss deduction — it is NOT deferred."""
        sale_date = date(2025, 6, 15)
        # Purchase in Roth 10 days after sale
        roth_purchase = Transaction(
            ticker="AAPL",
            trade_date=date(2025, 6, 25),
            shares=Decimal("10"),
            price_per_share=Decimal("150.00"),
            account_type=AccountType.ROTH,
            account_id="roth-001",
            is_drip=False,
        )

        result = scan_all_accounts(
            ticker="AAPL",
            sale_date=sale_date,
            transactions=[roth_purchase],
            sale_account_type=AccountType.TAXABLE,
        )

        assert result.is_wash_sale is True
        assert result.loss_type == LossType.PERMANENT
        assert result.triggering_purchase == roth_purchase

    def test_taxable_sale_ira_purchase_is_permanent(self):
        """Traditional IRA purchase also makes the loss permanent."""
        sale_date = date(2025, 6, 15)
        ira_purchase = Transaction(
            ticker="MSFT",
            trade_date=date(2025, 6, 10),
            shares=Decimal("5"),
            price_per_share=Decimal("400.00"),
            account_type=AccountType.TRADITIONAL_IRA,
            account_id="ira-001",
            is_drip=False,
        )

        result = scan_all_accounts(
            ticker="MSFT",
            sale_date=sale_date,
            transactions=[ira_purchase],
            sale_account_type=AccountType.TAXABLE,
        )

        assert result.is_wash_sale is True
        assert result.loss_type == LossType.PERMANENT

    def test_same_account_purchase_is_deferred(self):
        """Same-account wash sale is deferred (added to basis), not permanent."""
        sale_date = date(2025, 6, 15)
        taxable_purchase = Transaction(
            ticker="AAPL",
            trade_date=date(2025, 6, 20),
            shares=Decimal("10"),
            price_per_share=Decimal("150.00"),
            account_type=AccountType.TAXABLE,
            account_id="tax-001",
            is_drip=False,
        )

        result = scan_all_accounts(
            ticker="AAPL",
            sale_date=sale_date,
            transactions=[taxable_purchase],
            sale_account_type=AccountType.TAXABLE,
        )

        assert result.is_wash_sale is True
        assert result.loss_type == LossType.DEFERRED

    def test_no_wash_sale_outside_window(self):
        """Purchase 31 days after is outside the window."""
        sale_date = date(2025, 6, 15)
        late_purchase = Transaction(
            ticker="AAPL",
            trade_date=sale_date + timedelta(days=31),
            shares=Decimal("10"),
            price_per_share=Decimal("150.00"),
            account_type=AccountType.ROTH,
            account_id="roth-001",
            is_drip=False,
        )

        result = scan_all_accounts(
            ticker="AAPL",
            sale_date=sale_date,
            transactions=[late_purchase],
            sale_account_type=AccountType.TAXABLE,
        )

        assert result.is_wash_sale is False

    def test_purchase_30_days_before_triggers_wash_sale(self):
        """Purchase exactly 30 days before the sale is inside the window."""
        sale_date = date(2025, 6, 15)
        early_purchase = Transaction(
            ticker="AAPL",
            trade_date=sale_date - timedelta(days=30),
            shares=Decimal("5"),
            price_per_share=Decimal("145.00"),
            account_type=AccountType.ROTH,
            account_id="roth-001",
            is_drip=False,
        )

        result = scan_all_accounts(
            ticker="AAPL",
            sale_date=sale_date,
            transactions=[early_purchase],
            sale_account_type=AccountType.TAXABLE,
        )

        assert result.is_wash_sale is True
        assert result.loss_type == LossType.PERMANENT


class TestDRIPCountsAsPurchase:
    """Dividend reinvestment counts as a purchase for wash sale purposes."""

    def test_drip_triggers_wash_sale(self):
        """DRIP in any account within the window triggers a wash sale."""
        sale_date = date(2025, 6, 15)
        drip_txn = Transaction(
            ticker="JNJ",
            trade_date=date(2025, 6, 20),
            shares=Decimal("0.500000"),
            price_per_share=Decimal("160.00"),
            account_type=AccountType.TAXABLE,
            account_id="tax-001",
            is_drip=True,
        )

        result = scan_all_accounts(
            ticker="JNJ",
            sale_date=sale_date,
            transactions=[drip_txn],
            sale_account_type=AccountType.TAXABLE,
        )

        assert result.is_wash_sale is True
        assert result.triggering_purchase is not None
        assert result.triggering_purchase.is_drip is True

    def test_drip_in_roth_is_permanent(self):
        """DRIP in a Roth account = cross-account = permanent loss."""
        sale_date = date(2025, 6, 15)
        drip_txn = Transaction(
            ticker="JNJ",
            trade_date=date(2025, 6, 18),
            shares=Decimal("0.250000"),
            price_per_share=Decimal("160.00"),
            account_type=AccountType.ROTH,
            account_id="roth-001",
            is_drip=True,
        )

        result = scan_all_accounts(
            ticker="JNJ",
            sale_date=sale_date,
            transactions=[drip_txn],
            sale_account_type=AccountType.TAXABLE,
        )

        assert result.is_wash_sale is True
        assert result.loss_type == LossType.PERMANENT
        assert result.triggering_purchase.is_drip is True


class TestDisallowedLossAddedToBasis:
    """Disallowed loss is ADDED to the replacement lot's basis."""

    def test_basis_adjustment(self):
        """Disallowed $500 loss added to replacement lot's $1500 basis = $2000."""
        replacement_lot = TaxLot(
            lot_id="lot-new-001",
            ticker="AAPL",
            shares=Decimal("10"),
            cost_basis=Decimal("1500.00"),
            purchase_date=date(2025, 6, 20),
            account_type=AccountType.TAXABLE,
            account_id="tax-001",
        )

        adjusted = adjust_basis_for_wash_sale(
            replacement_lot=replacement_lot,
            disallowed_loss=Decimal("500.00"),
            original_purchase_date=date(2025, 1, 10),
        )

        assert adjusted.adjusted_basis == Decimal("2000.00")

    def test_basis_adjustment_precise(self):
        """Verify Decimal precision is maintained."""
        replacement_lot = TaxLot(
            lot_id="lot-new-002",
            ticker="MSFT",
            shares=Decimal("3.456789"),
            cost_basis=Decimal("1234.567890"),
            purchase_date=date(2025, 7, 1),
            account_type=AccountType.TAXABLE,
            account_id="tax-001",
        )

        adjusted = adjust_basis_for_wash_sale(
            replacement_lot=replacement_lot,
            disallowed_loss=Decimal("89.012345"),
            original_purchase_date=date(2025, 3, 15),
        )

        assert adjusted.adjusted_basis == Decimal("1323.580235")

    def test_disallowed_loss_must_be_non_negative(self):
        """Cannot have a negative disallowed loss."""
        replacement_lot = TaxLot(
            lot_id="lot-001",
            ticker="AAPL",
            shares=Decimal("10"),
            cost_basis=Decimal("1500.00"),
            purchase_date=date(2025, 6, 20),
            account_type=AccountType.TAXABLE,
            account_id="tax-001",
        )

        import pytest

        with pytest.raises(ValueError, match="non-negative"):
            adjust_basis_for_wash_sale(
                replacement_lot=replacement_lot,
                disallowed_loss=Decimal("-100.00"),
                original_purchase_date=date(2025, 1, 10),
            )


class TestHoldingPeriodInherited:
    """Holding period of replacement lot inherits from original lot."""

    def test_holding_period_inherited_from_original(self):
        """Replacement lot's holding period starts at the ORIGINAL purchase date."""
        original_purchase = date(2024, 3, 15)
        replacement_lot = TaxLot(
            lot_id="lot-new-001",
            ticker="AAPL",
            shares=Decimal("10"),
            cost_basis=Decimal("1500.00"),
            purchase_date=date(2025, 6, 20),  # Recent purchase
            account_type=AccountType.TAXABLE,
            account_id="tax-001",
        )

        adjusted = adjust_basis_for_wash_sale(
            replacement_lot=replacement_lot,
            disallowed_loss=Decimal("300.00"),
            original_purchase_date=original_purchase,
        )

        # Holding period start is the original purchase date, NOT the replacement date
        assert adjusted.holding_period_start == original_purchase
        assert adjusted.holding_period_start != replacement_lot.purchase_date

    def test_inherited_period_makes_long_term(self):
        """If original was held > 1 year, replacement inherits that and is long-term."""
        # Original purchased over a year ago
        original_purchase = date(2024, 1, 1)
        # Replacement purchased recently
        replacement_lot = TaxLot(
            lot_id="lot-new-002",
            ticker="MSFT",
            shares=Decimal("5"),
            cost_basis=Decimal("2000.00"),
            purchase_date=date(2025, 6, 25),
            account_type=AccountType.TAXABLE,
            account_id="tax-001",
        )

        adjusted = adjust_basis_for_wash_sale(
            replacement_lot=replacement_lot,
            disallowed_loss=Decimal("200.00"),
            original_purchase_date=original_purchase,
        )

        # Holding period is from 2024-01-01, so by 2025-06-25 it's long-term
        holding_days = (replacement_lot.purchase_date - adjusted.holding_period_start).days
        assert holding_days > 365


class TestRefuseIfWanted:
    """Refuses to harvest a name the screen wants this quarter."""

    def test_refuses_wanted_ticker(self):
        """If the screen wants to buy AAPL, do not harvest AAPL."""
        wanted = {"AAPL", "MSFT", "GOOG"}
        assert refuse_if_wanted("AAPL", wanted) is True

    def test_allows_unwanted_ticker(self):
        """If the screen does not want TSLA, harvesting is allowed."""
        wanted = {"AAPL", "MSFT", "GOOG"}
        assert refuse_if_wanted("TSLA", wanted) is False

    def test_empty_wanted_set_allows_all(self):
        """If screen wants nothing, all harvests are permitted."""
        assert refuse_if_wanted("AAPL", set()) is False

    def test_harvest_opportunity_refuses_wanted(self):
        """Full integration: harvest_opportunity returns None for wanted names."""
        lot = TaxLot(
            lot_id="lot-001",
            ticker="AAPL",
            shares=Decimal("10"),
            cost_basis=Decimal("2000.00"),
            purchase_date=date(2024, 6, 1),
            account_type=AccountType.TAXABLE,
            account_id="tax-001",
        )
        # Price is below cost basis (loss exists)
        result = harvest_opportunity(
            lot=lot,
            current_price=Decimal("150.00"),
            ticker_sector="Information Technology",
            wanted_tickers={"AAPL"},  # Screen wants AAPL
            all_transactions=[],
            sale_date=date(2025, 6, 15),
        )
        assert result is None


class TestReplacementETF:
    """Replacement is a sector ETF proxy."""

    def test_technology_sector_maps_to_xlk(self):
        assert replacement_etf("Information Technology") == "XLK"

    def test_health_care_maps_to_xlv(self):
        assert replacement_etf("Health Care") == "XLV"

    def test_financials_maps_to_xlf(self):
        assert replacement_etf("Financials") == "XLF"

    def test_energy_maps_to_xle(self):
        assert replacement_etf("Energy") == "XLE"

    def test_unknown_sector_returns_none(self):
        assert replacement_etf("Imaginary Sector") is None

    def test_all_gics_sectors_have_mapping(self):
        """Every GICS sector in the map resolves to a valid ETF ticker."""
        for _sector, etf in GICS_SECTOR_TO_ETF.items():
            assert etf is not None
            assert len(etf) >= 3  # Valid ticker

    def test_harvest_opportunity_uses_sector_etf(self):
        """harvest_opportunity populates replacement_etf from sector."""
        lot = TaxLot(
            lot_id="lot-001",
            ticker="AAPL",
            shares=Decimal("10"),
            cost_basis=Decimal("2000.00"),
            purchase_date=date(2024, 6, 1),
            account_type=AccountType.TAXABLE,
            account_id="tax-001",
        )
        result = harvest_opportunity(
            lot=lot,
            current_price=Decimal("150.00"),  # Loss of $500
            ticker_sector="Information Technology",
            wanted_tickers=set(),
            all_transactions=[],
            sale_date=date(2025, 6, 15),
        )
        assert result is not None
        assert result.replacement_etf == "XLK"


class TestTaxableOnly:
    """Only harvests in taxable accounts — never in Roth or IRA."""

    def test_roth_lot_not_harvested(self):
        lot = TaxLot(
            lot_id="lot-roth-001",
            ticker="AAPL",
            shares=Decimal("10"),
            cost_basis=Decimal("2000.00"),
            purchase_date=date(2024, 6, 1),
            account_type=AccountType.ROTH,
            account_id="roth-001",
        )
        result = harvest_opportunity(
            lot=lot,
            current_price=Decimal("150.00"),
            ticker_sector="Information Technology",
            wanted_tickers=set(),
            all_transactions=[],
            sale_date=date(2025, 6, 15),
        )
        assert result is None

    def test_ira_lot_not_harvested(self):
        lot = TaxLot(
            lot_id="lot-ira-001",
            ticker="MSFT",
            shares=Decimal("5"),
            cost_basis=Decimal("2500.00"),
            purchase_date=date(2024, 6, 1),
            account_type=AccountType.TRADITIONAL_IRA,
            account_id="ira-001",
        )
        result = harvest_opportunity(
            lot=lot,
            current_price=Decimal("400.00"),
            ticker_sector="Information Technology",
            wanted_tickers=set(),
            all_transactions=[],
            sale_date=date(2025, 6, 15),
        )
        assert result is None

    def test_taxable_lot_with_loss_is_harvested(self):
        lot = TaxLot(
            lot_id="lot-tax-001",
            ticker="AAPL",
            shares=Decimal("10"),
            cost_basis=Decimal("2000.00"),
            purchase_date=date(2024, 6, 1),
            account_type=AccountType.TAXABLE,
            account_id="tax-001",
        )
        result = harvest_opportunity(
            lot=lot,
            current_price=Decimal("150.00"),  # Market value $1500, loss $500
            ticker_sector="Information Technology",
            wanted_tickers=set(),
            all_transactions=[],
            sale_date=date(2025, 6, 15),
        )
        assert result is not None
        assert result.unrealized_loss == Decimal("500.00")


class TestScanWithLoss:
    """scan_all_accounts_with_loss fills in the disallowed amount."""

    def test_disallowed_amount_filled(self):
        sale_date = date(2025, 6, 15)
        roth_purchase = Transaction(
            ticker="AAPL",
            trade_date=date(2025, 6, 20),
            shares=Decimal("10"),
            price_per_share=Decimal("150.00"),
            account_type=AccountType.ROTH,
            account_id="roth-001",
            is_drip=False,
        )

        result = scan_all_accounts_with_loss(
            ticker="AAPL",
            sale_date=sale_date,
            loss_amount=Decimal("750.00"),
            transactions=[roth_purchase],
            sale_account_type=AccountType.TAXABLE,
        )

        assert result.is_wash_sale is True
        assert result.disallowed_amount == Decimal("750.00")
        assert result.loss_type == LossType.PERMANENT

    def test_no_wash_sale_disallowed_is_zero(self):
        sale_date = date(2025, 6, 15)

        result = scan_all_accounts_with_loss(
            ticker="AAPL",
            sale_date=sale_date,
            loss_amount=Decimal("750.00"),
            transactions=[],
            sale_account_type=AccountType.TAXABLE,
        )

        assert result.is_wash_sale is False
        assert result.disallowed_amount == Decimal("0")


class TestHarvestOpportunityNoWallClock:
    """harvest_opportunity must never read date.today() internally (no-lookahead rule 4).

    The proposed sale date is the caller's responsibility (e.g. a CLI's --as-of flag,
    defaulting to date.today() only at that boundary) -- never a wall-clock read buried
    inside pure logic.
    """

    def test_sale_date_is_a_required_parameter(self):
        """The function signature must not default sale_date to date.today()."""
        import inspect

        sig = inspect.signature(harvest_opportunity)
        assert "sale_date" in sig.parameters
        assert sig.parameters["sale_date"].default is inspect.Parameter.empty, (
            "sale_date must have no default -- a default of date.today() (or any "
            "wall-clock read) inside this function would violate no-lookahead rule 4."
        )

    def test_wash_sale_window_is_anchored_to_the_passed_sale_date_not_today(self):
        """A purchase within 61 days of the EXPLICIT sale_date triggers a wash sale, even
        though that date is nowhere near the real wall-clock 'today'. If the function read
        date.today() internally instead of using its sale_date argument, this purchase
        (dated 2020-01-20) would fall far outside a window centered on the real today and
        no wash sale would be detected -- so this test would fail the moment the
        date.today() placeholder crept back in."""
        explicit_sale_date = date(2020, 1, 15)
        same_account_purchase = Transaction(
            ticker="AAPL",
            trade_date=date(2020, 1, 20),  # 5 days after the explicit sale date
            shares=Decimal("10"),
            price_per_share=Decimal("150.00"),
            account_type=AccountType.TAXABLE,
            account_id="tax-001",
            is_drip=False,
        )
        lot = TaxLot(
            lot_id="lot-2020-001",
            ticker="AAPL",
            shares=Decimal("10"),
            cost_basis=Decimal("2000.00"),
            purchase_date=date(2019, 6, 1),
            account_type=AccountType.TAXABLE,
            account_id="tax-001",
        )

        result = harvest_opportunity(
            lot=lot,
            current_price=Decimal("150.00"),  # loss of $500
            ticker_sector="Information Technology",
            wanted_tickers=set(),
            all_transactions=[same_account_purchase],
            sale_date=explicit_sale_date,
        )

        assert result is not None
        assert result.wash_sale_risk is not None
        assert result.wash_sale_risk.is_wash_sale is True
        assert result.wash_sale_risk.loss_type == LossType.DEFERRED

    def test_no_purchase_near_today_does_not_leak_into_a_past_sale_date(self):
        """A purchase dated near the real wall-clock 'today' must NOT trigger a wash sale
        for a harvest proposed years in the past -- proving the window is built from the
        passed sale_date only."""
        explicit_sale_date = date(2020, 1, 15)
        purchase_near_real_today = Transaction(
            ticker="AAPL",
            trade_date=date.today(),
            shares=Decimal("10"),
            price_per_share=Decimal("150.00"),
            account_type=AccountType.TAXABLE,
            account_id="tax-001",
            is_drip=False,
        )
        lot = TaxLot(
            lot_id="lot-2020-002",
            ticker="AAPL",
            shares=Decimal("10"),
            cost_basis=Decimal("2000.00"),
            purchase_date=date(2019, 6, 1),
            account_type=AccountType.TAXABLE,
            account_id="tax-001",
        )

        result = harvest_opportunity(
            lot=lot,
            current_price=Decimal("150.00"),
            ticker_sector="Information Technology",
            wanted_tickers=set(),
            all_transactions=[purchase_near_real_today],
            sale_date=explicit_sale_date,
        )

        assert result is not None
        assert result.wash_sale_risk is None
