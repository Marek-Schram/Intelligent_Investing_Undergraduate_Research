"""After-tax-optimal lot selection wired to harvest opportunities. TICKET-035/036.

Bridges the two dataclass families this package already has, tested and complete:
  - `tax.harvest.TaxLot` / `tax.harvest.Transaction` -- whole-lot, account-aware
    dataclasses used for wash-sale detection and harvest eligibility.
  - `tax.lots.Lot` / `tax.lots.select_lots` -- per-share, `Decimal`-precise, after-tax
    optimal selection primitives (TICKET-035), already implemented and tested in
    `tax/lots.py` / `tests/test_lots.py`.

This module does not re-implement lot selection. It converts a ticker's taxable
`harvest.TaxLot` rows into `lots.Lot` objects, determines wash-sale risk for the
proposed sale by calling `harvest.scan_all_accounts` (rule 2: scanned across ALL
accounts, not just the selling one), and calls `tax.lots.select_lots` under
TAX_OPTIMAL, FIFO, and HIFO strategies so the caller can see -- in dollars, by
lot_id -- exactly which specific lots the after-tax-optimal choice sells and why
that beats a naive default. Every result carries `tax.lots.select_lots`'s own
per-lot reason strings (rule 9: a CPA must be able to reconstruct the selection),
plus a consolidated explanation logged here.

Data source: in-memory lot/transaction records (no I/O; caller loads them).
available_at logic: every lot/transaction the caller passes in is assumed already
    point-in-time filtered by the caller (see harvest.py's CLI section for how the
    tax-review command does that against the `tax_lots` table).
Spec section: docs/11 sections 2-3.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from durable.tax.harvest import (
    AccountType,
    TaxLot,
    Transaction,
    scan_all_accounts,
)
from durable.tax.lots import (
    Lot,
    LotSelection,
    LotSelectionResult,
    TaxRates,
    WashSaleRisk,
    select_lots,
)

logger = logging.getLogger(__name__)

_SIX_DP = Decimal("0.000001")


def harvest_lot_to_lot(tax_lot: TaxLot, *, sleeve: str = "C") -> Lot:
    """Convert a whole-lot `harvest.TaxLot` into a per-share `lots.Lot`.

    `harvest.TaxLot.cost_basis` is the total dollar basis for the lot; `lots.Lot`
    wants a per-share basis plus a total `adjusted_basis`. Both are already `Decimal`
    in `harvest.TaxLot` (a frozen dataclass with `Decimal` fields), so no float ever
    touches this conversion. `shares` is re-quantized to 6 decimal places to satisfy
    `Lot.__post_init__`'s precision check even if the caller's Decimal carried extra
    (zero) trailing exponent.

    Args:
        tax_lot: The whole-lot record to convert.
        sleeve: Sleeve label to attach (informational only; `Lot` requires it but
            `TaxLot` doesn't carry it).

    Returns:
        An open `Lot` (`closed_at=None`) with `holding_start=None`, i.e. the holding
        period runs from `acquired_at` -- callers that need wash-sale-inherited
        holding periods must pass a `TaxLot` whose `purchase_date` already reflects
        that inheritance (see `adjust_basis_for_wash_sale`).
    """
    if tax_lot.shares <= Decimal("0"):
        msg = f"Lot {tax_lot.lot_id} has non-positive shares: {tax_lot.shares}"
        raise ValueError(msg)

    shares = tax_lot.shares.quantize(_SIX_DP)
    cost_basis_per_share = (tax_lot.cost_basis / tax_lot.shares).quantize(_SIX_DP)

    return Lot(
        lot_id=tax_lot.lot_id,
        ticker=tax_lot.ticker,
        sleeve=sleeve,
        account=tax_lot.account_type.value,
        acquired_at=tax_lot.purchase_date,
        shares=shares,
        cost_basis_per_share=cost_basis_per_share,
        adjusted_basis=tax_lot.cost_basis,
        closed_at=None,
    )


def wash_sale_risk_for_ticker(
    ticker: str,
    sale_date: date,
    all_transactions: list[Transaction],
    sale_account_type: AccountType,
) -> WashSaleRisk | None:
    """Determine wash-sale risk for a proposed sale of `ticker`, scanning ALL accounts.

    The wash-sale rule taints the LOSS realized on a sale of a given ticker within the
    61-day window -- it does not depend on which specific lot the loss is realized
    from. So one `harvest.scan_all_accounts` result for (ticker, sale_date) applies
    uniformly to every open lot of that ticker under consideration for this sale.

    Data source: transaction records across ALL accounts (taxable, Roth, IRA).
    available_at logic: as of trade date, per transaction.
    Spec section: docs/11 section 5.

    Returns:
        None if no wash sale is triggered; otherwise a `lots.WashSaleRisk` describing it.
    """
    result = scan_all_accounts(ticker, sale_date, all_transactions, sale_account_type)
    if not result.is_wash_sale:
        return None

    conflicting_id = "unknown triggering purchase"
    if result.triggering_purchase is not None:
        txn = result.triggering_purchase
        conflicting_id = f"{txn.ticker}@{txn.trade_date.isoformat()}:{txn.account_type.value}"

    return WashSaleRisk(at_risk=True, conflicting_lot_id=conflicting_id, reason=result.explanation)


def _after_tax_proceeds_of_selection(
    selection_results: list[LotSelectionResult],
    current_price: Decimal,
    sale_date: date,
    tax_rates: TaxRates,
    wash_sale_risks: dict[str, WashSaleRisk],
) -> Decimal:
    """Sum after-tax proceeds across a `select_lots` result, honoring wash-sale disallowance.

    Mirrors `tax.lots._compute_tax_cost`'s treatment: for each lot, if
    `wash_sale_risks[lot.lot_id].at_risk` and that lot's realized amount is a loss, the
    loss produces no tax benefit (disallowed). Gains are unaffected. Risk is looked up
    per lot_id, not applied uniformly, so a caller-supplied override (see
    `select_after_tax_optimal_harvest_lots`'s `wash_sale_risk_overrides`) can mark only
    specific lots as tainted.
    """
    total = Decimal("0")
    for r in selection_results:
        basis_per_share = r.lot.adjusted_basis / r.lot.shares
        gain = (current_price - basis_per_share) * r.shares_to_sell
        is_lt = r.lot.is_long_term(sale_date)
        rate = tax_rates.effective_lt_rate if is_lt else tax_rates.effective_st_rate
        tax = gain * rate
        risk = wash_sale_risks.get(r.lot.lot_id)
        if risk is not None and risk.at_risk and gain < Decimal("0"):
            tax = Decimal("0")
        total += current_price * r.shares_to_sell - tax
    return total


@dataclass(frozen=True)
class LotSelectionComparison:
    """Which specific lots the after-tax-optimal choice sells, and why it wins.

    Every field needed to reconstruct the decision (rule 9) is here: the exact
    `lot_id`s and share counts under each strategy, and the after-tax proceeds each
    strategy would produce for the identical sale.
    """

    ticker: str
    sale_date: date
    shares_sold: Decimal
    tax_optimal: list[LotSelectionResult]
    naive_fifo: list[LotSelectionResult]
    naive_hifo: list[LotSelectionResult]
    after_tax_proceeds_optimal: Decimal
    after_tax_proceeds_fifo: Decimal
    after_tax_proceeds_hifo: Decimal
    tax_alpha_vs_fifo: Decimal  # optimal - fifo; positive means optimal is better
    tax_alpha_vs_hifo: Decimal  # optimal - hifo; positive means optimal is better
    wash_sale_risks: dict[str, WashSaleRisk]  # by lot_id; empty if no risk detected
    explanation: str


def select_after_tax_optimal_harvest_lots(
    ticker: str,
    taxable_lots: list[TaxLot],
    current_price: Decimal,
    sale_date: date,
    tax_rates: TaxRates,
    all_transactions: list[Transaction],
    *,
    sale_account_type: AccountType = AccountType.TAXABLE,
    shares_to_sell: Decimal | None = None,
    sleeve: str = "C",
    wash_sale_risk_overrides: dict[str, WashSaleRisk] | None = None,
) -> LotSelectionComparison:
    """Pick the specific lots to sell for `ticker`, maximizing after-tax proceeds.

    Data source: in-memory `harvest.TaxLot` / `harvest.Transaction` records (caller
    already point-in-time filtered these; see `harvest.py`'s CLI section).
    available_at logic: `sale_date` is threaded through every holding-period and
        wash-sale calculation; nothing here reads the wall clock.
    Spec section: docs/11 sections 3 and 5.

    Wash-sale risk defaults to the CONSERVATIVE assumption: if `harvest.scan_all_accounts`
    finds ANY same-ticker purchase in the 61-day window (across ALL accounts, rule 2),
    every candidate lot's loss is treated as at risk. This never under-reports a wash
    sale, which is the safer failure mode -- a tax bug that silently claims a
    disallowed deduction costs real money a year later. In reality, IRS Pub. 550's
    share-matching can leave PART of a multi-lot sale's loss allowed (disallowance is
    capped at the number of replacement shares actually purchased); when the caller has
    that finer-grained information, `wash_sale_risk_overrides` lets them mark only the
    specific lot_ids affected instead of the whole ticker.

    Args:
        ticker: The ticker being sold. All `taxable_lots` must match.
        taxable_lots: Open lots of `ticker` in the selling account (rule 6: never
            pass Roth/IRA lots here -- this function does not gate on account type
            itself; the caller, `harvest.build_tax_review`, only ever supplies
            taxable lots).
        current_price: Current market price per share.
        sale_date: Proposed sale date.
        tax_rates: Marginal short-term/long-term rates.
        all_transactions: ALL transactions across ALL accounts, for wash-sale scanning.
        sale_account_type: Account the sale occurs in. Defaults to TAXABLE.
        shares_to_sell: Shares to sell. Defaults to every share across `taxable_lots`
            (a full exit), which is the usual case for a harvest sale.
        sleeve: Sleeve label to attach to the converted `Lot`s (informational).
        wash_sale_risk_overrides: Optional `{lot_id: WashSaleRisk}` replacing the
            automatic ticker-wide scan when the caller has lot-specific information.

    Returns:
        A `LotSelectionComparison` naming the specific lots to sell under each
        strategy and the after-tax proceeds each would produce.

    Raises:
        ValueError: If `taxable_lots` is empty, mixes tickers/accounts, or
            `shares_to_sell` exceeds what's available.
        TypeError: If `shares_to_sell` is supplied but isn't a `Decimal`.
    """
    if not taxable_lots:
        msg = f"No lots supplied for {ticker}"
        raise ValueError(msg)
    if any(lot.ticker != ticker for lot in taxable_lots):
        msg = f"select_after_tax_optimal_harvest_lots: all lots must be for {ticker}"
        raise ValueError(msg)
    if any(lot.account_type != sale_account_type for lot in taxable_lots):
        msg = (
            "select_after_tax_optimal_harvest_lots: all lots must be in the "
            f"selling account ({sale_account_type.value})"
        )
        raise ValueError(msg)

    converted = [harvest_lot_to_lot(lot, sleeve=sleeve) for lot in taxable_lots]
    total_shares = sum((lot.shares for lot in converted), Decimal("0"))

    if shares_to_sell is None:
        sell_qty = total_shares
    else:
        if not isinstance(shares_to_sell, Decimal):
            msg = f"shares_to_sell must be Decimal, got {type(shares_to_sell).__name__}"
            raise TypeError(msg)
        sell_qty = shares_to_sell
    if sell_qty > total_shares:
        msg = f"Need {sell_qty} shares of {ticker} but only {total_shares} across supplied lots"
        raise ValueError(msg)

    if wash_sale_risk_overrides is not None:
        wash_sale_risks = wash_sale_risk_overrides
    else:
        auto_risk = wash_sale_risk_for_ticker(
            ticker, sale_date, all_transactions, sale_account_type
        )
        wash_sale_risks = (
            {lot.lot_id: auto_risk for lot in converted} if auto_risk is not None else {}
        )

    tax_optimal = select_lots(
        lots=converted,
        shares_needed=sell_qty,
        current_price=current_price,
        sale_date=sale_date,
        strategy=LotSelection.TAX_OPTIMAL,
        tax_rates=tax_rates,
        wash_sale_risks=wash_sale_risks or None,
    )
    naive_fifo = select_lots(
        lots=converted,
        shares_needed=sell_qty,
        current_price=current_price,
        sale_date=sale_date,
        strategy=LotSelection.FIFO,
    )
    naive_hifo = select_lots(
        lots=converted,
        shares_needed=sell_qty,
        current_price=current_price,
        sale_date=sale_date,
        strategy=LotSelection.HIFO,
    )

    proceeds_optimal = _after_tax_proceeds_of_selection(
        tax_optimal, current_price, sale_date, tax_rates, wash_sale_risks
    )
    proceeds_fifo = _after_tax_proceeds_of_selection(
        naive_fifo, current_price, sale_date, tax_rates, wash_sale_risks
    )
    proceeds_hifo = _after_tax_proceeds_of_selection(
        naive_hifo, current_price, sale_date, tax_rates, wash_sale_risks
    )

    alpha_fifo = proceeds_optimal - proceeds_fifo
    alpha_hifo = proceeds_optimal - proceeds_hifo

    lot_summary = ", ".join(f"{r.lot.lot_id}:{r.shares_to_sell}sh" for r in tax_optimal)
    explanation = (
        f"TAX_OPTIMAL sells [{lot_summary}] of {ticker} on {sale_date.isoformat()}: "
        f"after-tax proceeds ${proceeds_optimal} vs naive FIFO ${proceeds_fifo} "
        f"(alpha ${alpha_fifo}) vs naive HIFO ${proceeds_hifo} (alpha ${alpha_hifo})."
    )
    if wash_sale_risks:
        tainted = ", ".join(sorted(wash_sale_risks))
        explanation += f" Wash-sale risk on lot(s) [{tainted}]."
    logger.info(explanation)

    return LotSelectionComparison(
        ticker=ticker,
        sale_date=sale_date,
        shares_sold=sell_qty,
        tax_optimal=tax_optimal,
        naive_fifo=naive_fifo,
        naive_hifo=naive_hifo,
        after_tax_proceeds_optimal=proceeds_optimal,
        after_tax_proceeds_fifo=proceeds_fifo,
        after_tax_proceeds_hifo=proceeds_hifo,
        tax_alpha_vs_fifo=alpha_fifo,
        tax_alpha_vs_hifo=alpha_hifo,
        wash_sale_risks=wash_sale_risks,
        explanation=explanation,
    )
