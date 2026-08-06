"""Order submission. Human-gated (CLAUDE.md non-negotiable #4). TICKET-016.

Every constraint here is re-validated independently of the proposal file — this module
does not trust `propose.py`'s output (.claude/rules/money-safety.md rule 5). A hook
(`.claude/hooks/guard_bash.sh`) blocks Claude Code from ever invoking this module or
passing `--i-have-read-the-proposal`; only a human, from their own terminal or the GUI's
Submit page (after typing "I APPROVE"), can run it.

Real Alpaca connectivity is NOT implemented here or in `execution/broker.py` (see that
module's `submit_limit_order` — it validates every safety constraint but returns a
simulated result rather than making an HTTP call). Wiring a real broker API call is a
separate, larger ticket that needs its own careful review; until then this CLI always
runs with `dry_run=True` so it can never be mistaken for placing a real order.

Data source: a proposal JSON file written by `execution/propose.py`, plus the local PIT
store for lot acquisition dates (holding-period re-validation).
available_at logic: not applicable — this module reads current portfolio state, not
point-in-time market data.
Spec section: SPEC §9, CLAUDE.md non-negotiables #1-#5, .claude/rules/money-safety.md.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MIN_HOLDING_DAYS = 365  # CLAUDE.md non-negotiable #5


@dataclass
class BlockedTrade:
    ticker: str
    action: str
    reason: str


@dataclass
class SubmissionResult:
    submitted: list[dict] = field(default_factory=list)
    blocked: list[BlockedTrade] = field(default_factory=list)
    dry_run: bool = True


def revalidate_trade(trade: dict, config: dict, lot_acquired_at: dict[str, date]) -> str | None:
    """Re-check a single trade independently of whatever propose.py already decided.
    Returns None if it passes, else a human-readable reason it was blocked.

    This does NOT re-trust `trade["sell_rule"]` being present as sufficient — it recomputes
    the one check that's cheap and critical to re-derive here: the 12-month minimum holding
    period (CLAUDE.md non-negotiable #5). Order-shape checks (limit-only, explicit lot_ids,
    notional ceiling) are re-validated again downstream by `broker.submit_limit_order` itself
    (rule 5: submit re-validates independently — belt and suspenders, not a single check).
    """
    if trade["action"] not in ("buy", "sell", "trim"):
        return f"Unknown action {trade['action']!r}"

    if trade.get("limit_price") is None or trade["limit_price"] <= 0:
        return "No valid limit price — limit orders only, never market (money-safety rule 4)"

    if trade["action"] in ("sell", "trim"):
        if not trade.get("lot_ids"):
            return "Sell/trim has no lot_ids — never let the broker default to FIFO (rule 10)"
        if trade.get("sell_rule") is None:
            # No written sell rule fired: the only way this sale is allowed is if every lot
            # being sold has already cleared the 12-month minimum holding period.
            too_young = [
                lot_id
                for lot_id in trade["lot_ids"]
                if lot_id in lot_acquired_at
                and (date.fromisoformat(trade["as_of"]) - lot_acquired_at[lot_id]).days
                < MIN_HOLDING_DAYS
            ]
            if too_young:
                return (
                    f"No sell rule fired and lot(s) {too_young} are under the 12-month "
                    "minimum holding period (CLAUDE.md non-negotiable #5)"
                )

    max_notional = config.get("max_order_notional", 500)
    notional = abs(trade["shares"] * trade["limit_price"])
    if notional > max_notional:
        return f"Notional ${notional:,.2f} exceeds max_order_notional ${max_notional:,.2f}"

    return None


def _load_proposal(path: Path) -> dict:
    data = json.loads(path.read_text())
    for trade in data.get("trades", []):
        trade["as_of"] = data["as_of"]
    return data


def _lot_acquired_dates(conn, lot_ids: list[str]) -> dict[str, date]:
    if not lot_ids:
        return {}
    rows = conn.execute(
        "SELECT lot_id, acquired_at FROM tax_lots WHERE lot_id IN "
        f"({','.join('?' for _ in lot_ids)})",
        lot_ids,
    ).fetchall()
    return {lot_id: acquired_at for lot_id, acquired_at in rows}


def submit_proposal(
    proposal_path: Path, config: dict, conn, *, dry_run: bool = True
) -> SubmissionResult:
    """Re-validate and (dry-run) submit every trade in a proposal file.

    Rule 6: the caller MUST have already called `broker.assert_safe_to_trade` before this
    function is reached — that check happens once, in the CLI entry point below, before any
    file is even opened, exactly as money-safety.md rule 6 requires.
    """
    from durable.execution import broker

    proposal = _load_proposal(proposal_path)
    all_lot_ids = [lid for t in proposal["trades"] for lid in t.get("lot_ids", [])]
    lot_acquired_at = _lot_acquired_dates(conn, all_lot_ids)

    base_url = os.environ.get("ALPACA_PAPER_BASE_URL", "https://paper-api.alpaca.markets")
    live_trading_approved = bool(config.get("live_trading_approved", False))
    max_notional = config.get("max_order_notional", 500)

    result = SubmissionResult(dry_run=dry_run)
    for trade in proposal["trades"]:
        if trade["shares"] <= 0:
            continue  # nothing to do — e.g. a buy the CLI couldn't size (no known NAV)

        reason = revalidate_trade(trade, config, lot_acquired_at)
        if reason is not None:
            result.blocked.append(
                BlockedTrade(ticker=trade["ticker"], action=trade["action"], reason=reason)
            )
            continue

        side = "buy" if trade["action"] == "buy" else "sell"
        order = broker.submit_limit_order(
            symbol=trade["ticker"],
            qty=abs(trade["shares"]),
            side=side,
            limit_price=trade["limit_price"],
            base_url=base_url,
            lot_ids=trade.get("lot_ids") or None,
            dry_run=dry_run,
            max_notional=max_notional,
            live_trading_approved=live_trading_approved,
        )
        result.submitted.append(
            {
                "ticker": order.symbol,
                "qty": order.qty,
                "side": order.side,
                "limit_price": order.limit_price,
                "status": order.status,
                "order_id": order.order_id,
                "lot_ids": order.lot_ids,
            }
        )

    return result


def _write_audit_log(proposal_path: Path, result: SubmissionResult) -> Path:
    out_dir = PROJECT_ROOT / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"submission_{date.today().isoformat()}.json"
    # Never write API keys — nothing in `result` carries them (broker.py never receives
    # or handles them either; there is no real Alpaca call yet, see module docstring).
    out_path.write_text(
        json.dumps(
            {
                "proposal": str(proposal_path),
                "dry_run": result.dry_run,
                "submitted": result.submitted,
                "blocked": [b.__dict__ for b in result.blocked],
            },
            indent=2,
        )
    )
    return out_path


def _run_cli(proposal_arg: str, i_have_read_the_proposal: bool) -> int:
    if not i_have_read_the_proposal:
        print(
            "Refusing to run: pass --i-have-read-the-proposal only after you have opened "
            "the proposal file yourself and understand every trade it lists."
        )
        return 2

    from durable.config import ConfigError, load_config
    from durable.execution import broker

    try:
        config = load_config()
    except ConfigError as exc:
        print(str(exc))
        return 1

    # Rule 6: KILL/RECONCILE_FAILED/paper-api check FIRST — before opening the proposal file,
    # before touching the database, before anything else.
    base_url = os.environ.get("ALPACA_PAPER_BASE_URL", "https://paper-api.alpaca.markets")
    try:
        broker.assert_safe_to_trade(
            base_url=base_url,
            live_trading_approved=bool(config.get("live_trading_approved", False)),
            max_notional=config.get("max_order_notional", 500),
        )
    except (broker.KillSwitchError, broker.ReconcileFailedError, broker.PaperOnlyError) as exc:
        print(f"BLOCKED: {exc}")
        return 1

    proposal_path = Path(proposal_arg)
    if not proposal_path.is_absolute():
        proposal_path = PROJECT_ROOT / proposal_path
    if not proposal_path.is_file():
        print(f"Proposal file not found: {proposal_path}")
        return 1

    db_path = PROJECT_ROOT / "data" / "durable.duckdb"
    if not db_path.exists():
        print(f"No database at {db_path.relative_to(PROJECT_ROOT)} — nothing to submit against.")
        return 1

    from durable.data import store

    conn = store.get_conn(db_path)
    try:
        result = submit_proposal(proposal_path, config, conn, dry_run=True)
    finally:
        conn.close()

    print(
        "DRY RUN ONLY — real Alpaca connectivity is not wired up yet (see module docstring). "
        "No order actually left this machine."
    )
    print(f"{len(result.submitted)} trade(s) passed re-validation, {len(result.blocked)} blocked.")
    for b in result.blocked:
        print(f"  BLOCKED {b.ticker} ({b.action}): {b.reason}")
    audit_path = _write_audit_log(proposal_path, result)
    print(f"Wrote {audit_path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Submit a reviewed proposal. Human-only.")
    parser.add_argument("--proposal", required=True)
    parser.add_argument("--i-have-read-the-proposal", action="store_true")
    args = parser.parse_args()
    sys.exit(_run_cli(args.proposal, args.i_have_read_the_proposal))
