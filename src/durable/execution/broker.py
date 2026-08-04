"""Alpaca adapter. TICKET-015.

EVERY function that can move money takes `dry_run: bool = True`.
See .claude/rules/money-safety.md and .claude/hooks/guard_bash.sh.

assert_safe_to_trade(config) -> None. Fail closed, BEFORE authentication. Checks: KILL absent,
    RECONCILE_FAILED absent, 'paper-api' in URL unless live_trading_approved, notional limits.
submit_limit_order(symbol, qty, side, limit_price, *, lot_ids=None, dry_run=True) -> dict
    Limit orders only. No market orders, no shorts. Sells without lot_ids raise -- never let
    the broker default to FIFO.
"""

from __future__ import annotations
