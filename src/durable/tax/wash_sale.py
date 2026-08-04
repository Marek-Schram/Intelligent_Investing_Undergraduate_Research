"""Wash-sale engine. TICKET-036.

61-day window: 30 days before AND after, plus the sale date.

Three traps that cost real money:
  1. The rule reaches ACROSS ACCOUNTS including IRAs and a spouse's. Taxable sale + Roth
     purchase = PERMANENTLY LOST deduction, not deferred.
  2. Automatic dividend reinvestment counts as a purchase.
  3. The replacement's holding period inherits from the original lot.

check_wash_sale(ticker, sale_date, accounts, include_drip=True) -> dict
    `accounts` MUST include taxable, Roth, and traditional IRA. A subset is a bug.
apply_disallowance(disallowed, replacement_lot_id) -> None
    ADD to adjusted_basis and inherit holding_start. NEVER delete a disallowed loss --
    deleting it overstates lifetime tax paid and misstates every after-tax return.
"""

from __future__ import annotations
