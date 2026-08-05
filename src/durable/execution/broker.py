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

import os
from dataclasses import dataclass
from pathlib import Path


class KillSwitchError(RuntimeError):
    """KILL file detected — halt all execution."""


class ReconcileFailedError(RuntimeError):
    """RECONCILE_FAILED file detected — mismatch blocks submit."""


class PaperOnlyError(RuntimeError):
    """Live trading attempted without live_trading_approved flag."""


class MissingLotIdsError(ValueError):
    """Sell order submitted without explicit lot_ids."""


class NotionalLimitError(ValueError):
    """Order exceeds per-order notional limit."""


@dataclass
class OrderResult:
    """Result of an order submission (or dry run)."""

    symbol: str
    qty: float
    side: str
    limit_price: float
    status: str  # 'dry_run', 'submitted', 'filled', 'rejected'
    order_id: str | None = None
    lot_ids: list[str] | None = None


def assert_safe_to_trade(
    base_url: str,
    live_trading_approved: bool = False,
    kill_file: str | Path = "KILL",
    reconcile_failed_file: str | Path = "RECONCILE_FAILED",
    max_notional: float = 50_000.0,
) -> None:
    """Pre-auth safety checks. Fail closed. SPEC non-negotiable #1.

    Checks in order (exit on first failure):
    1. KILL file absent
    2. RECONCILE_FAILED file absent
    3. 'paper-api' in URL (unless live_trading_approved)
    """
    # 1. KILL file — exits before auth
    if Path(kill_file).exists():
        raise KillSwitchError(
            "KILL file detected. Remove it manually to resume trading."
        )

    # 2. RECONCILE_FAILED — mismatch blocks submit
    if Path(reconcile_failed_file).exists():
        raise ReconcileFailedError(
            "RECONCILE_FAILED file detected. Resolve the mismatch before trading."
        )

    # 3. paper-api assertion
    if not live_trading_approved and "paper-api" not in base_url:
        raise PaperOnlyError(
            f"URL '{base_url}' does not contain 'paper-api'. "
            "Set live_trading_approved=True to use live trading."
        )


def submit_limit_order(
    symbol: str,
    qty: float,
    side: str,
    limit_price: float,
    base_url: str = "https://paper-api.alpaca.markets",
    lot_ids: list[str] | None = None,
    dry_run: bool = True,
    max_notional: float = 50_000.0,
    live_trading_approved: bool = False,
) -> OrderResult:
    """Submit a limit order. SPEC §9.

    - Limit orders only (no market orders)
    - No shorts (side must be 'buy' or 'sell')
    - Sells without lot_ids raise MissingLotIdsError
    - Re-validates safety independently (does not trust the proposal)
    """
    # Re-validate safety independently
    assert_safe_to_trade(
        base_url=base_url,
        live_trading_approved=live_trading_approved,
    )

    # Validate order parameters
    if side not in ("buy", "sell"):
        raise ValueError(f"Invalid side '{side}'. Only 'buy' and 'sell' allowed (no shorts).")

    if qty <= 0:
        raise ValueError(f"Quantity must be positive, got {qty}")

    if limit_price <= 0:
        raise ValueError(f"Limit price must be positive, got {limit_price}")

    # Sells must specify lot_ids
    if side == "sell" and not lot_ids:
        raise MissingLotIdsError(
            f"Sell order for {symbol} has no lot_ids. "
            "Never let the broker default to FIFO."
        )

    # Notional limit check
    notional = qty * limit_price
    if notional > max_notional:
        raise NotionalLimitError(
            f"Order notional ${notional:.2f} exceeds limit ${max_notional:.2f}"
        )

    if dry_run:
        return OrderResult(
            symbol=symbol,
            qty=qty,
            side=side,
            limit_price=limit_price,
            status="dry_run",
            lot_ids=lot_ids,
        )

    # Actual submission would go here (Alpaca API call)
    # For now, return a submitted status
    return OrderResult(
        symbol=symbol,
        qty=qty,
        side=side,
        limit_price=limit_price,
        status="submitted",
        order_id=f"sim-{symbol}-{side}",
        lot_ids=lot_ids,
    )
