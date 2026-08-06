"""Tests for order submission. Human-gated, money-safety-critical. Hand-computed fixtures.

Note: `.claude/hooks/guard_bash.sh` blocks Claude Code from ever running
`python -m durable.execution.submit ... --i-have-read-the-proposal` directly -- these tests
call the module's functions in-process instead, which is not the same as invoking the CLI
and does not touch that guard.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from durable.data import store
from durable.execution.submit import (
    BlockedTrade,
    SubmissionResult,
    _lot_acquired_dates,
    _run_cli,
    _write_audit_log,
    revalidate_trade,
    submit_proposal,
)

CONFIG = {"live_trading_approved": False, "max_order_notional": 500}


def _trade(**overrides) -> dict:
    base = {
        "ticker": "AAPL",
        "action": "buy",
        "shares": 1.0,
        "limit_price": 100.0,
        "lot_ids": [],
        "sell_rule": None,
        "as_of": "2026-08-06",
    }
    base.update(overrides)
    return base


class TestRevalidateTrade:
    def test_valid_buy_passes(self):
        assert revalidate_trade(_trade(), CONFIG, {}) is None

    def test_unknown_action_rejected(self):
        reason = revalidate_trade(_trade(action="short"), CONFIG, {})
        assert reason is not None and "Unknown action" in reason

    def test_missing_limit_price_rejected(self):
        reason = revalidate_trade(_trade(limit_price=None), CONFIG, {})
        assert reason is not None and "limit price" in reason

    def test_zero_limit_price_rejected(self):
        reason = revalidate_trade(_trade(limit_price=0.0), CONFIG, {})
        assert reason is not None and "limit price" in reason

    def test_sell_without_lot_ids_rejected(self):
        """Rule 10: never let the broker default to FIFO."""
        reason = revalidate_trade(_trade(action="sell", lot_ids=[]), CONFIG, {})
        assert reason is not None and "lot_ids" in reason

    def test_sell_with_no_sell_rule_and_young_lot_rejected(self):
        """CLAUDE.md non-negotiable #5: min holding 12 months unless a written sell rule
        fires. Lot acquired 30 days before the proposed sale -- well under 365 days."""
        reason = revalidate_trade(
            _trade(action="sell", lot_ids=["lot1"], sell_rule=None, as_of="2026-08-06"),
            CONFIG,
            {"lot1": date(2026, 7, 7)},
        )
        assert reason is not None and "12-month" in reason

    def test_sell_with_no_sell_rule_but_old_lot_passes(self):
        """Lot acquired more than 365 days before the sale -- clears the minimum on its
        own, no written sell rule needed."""
        reason = revalidate_trade(
            _trade(action="sell", lot_ids=["lot1"], sell_rule=None, as_of="2026-08-06"),
            CONFIG,
            {"lot1": date(2024, 1, 1)},
        )
        assert reason is None

    def test_sell_with_written_sell_rule_skips_holding_period_check(self):
        """A written sell rule (e.g. S2 exclusion flag) authorizes selling a young lot."""
        reason = revalidate_trade(
            _trade(action="sell", lot_ids=["lot1"], sell_rule="S2", as_of="2026-08-06"),
            CONFIG,
            {"lot1": date(2026, 7, 7)},
        )
        assert reason is None

    def test_notional_over_limit_rejected(self):
        reason = revalidate_trade(
            _trade(shares=10.0, limit_price=100.0), CONFIG, {}
        )  # $1000 > $500 max
        assert reason is not None and "Notional" in reason

    def test_notional_at_limit_passes(self):
        reason = revalidate_trade(_trade(shares=5.0, limit_price=100.0), CONFIG, {})  # $500
        assert reason is None


class TestLotAcquiredDates:
    def test_empty_lot_ids_returns_empty(self):
        assert _lot_acquired_dates(None, []) == {}

    def test_looks_up_real_lots(self):
        conn = store.get_conn(":memory:")
        store.init_schema(conn)
        conn.execute(
            "INSERT INTO tax_lots (lot_id, ticker, sleeve, account, acquired_at, shares, "
            "cost_basis_per_share, holding_start) VALUES (?,?,?,?,?,?,?,?)",
            ["lot1", "AAPL", "C", "taxable", date(2024, 1, 1), 5.0, 100.0, date(2024, 1, 1)],
        )
        result = _lot_acquired_dates(conn, ["lot1", "lot-missing"])
        assert result == {"lot1": date(2024, 1, 1)}


class TestSubmitProposal:
    def _write_proposal(self, tmp_path: Path, trades: list[dict]) -> Path:
        path = tmp_path / "proposal_2026-08-06.json"
        path.write_text(json.dumps({"as_of": "2026-08-06", "trades": trades}))
        return path

    def test_dry_run_buy_recorded_as_submitted(self, tmp_path):
        conn = store.get_conn(":memory:")
        store.init_schema(conn)
        path = self._write_proposal(
            tmp_path,
            [
                {
                    "ticker": "AAPL",
                    "action": "buy",
                    "shares": 1.0,
                    "limit_price": 100.0,
                    "lot_ids": [],
                    "sell_rule": None,
                }
            ],
        )
        result = submit_proposal(path, CONFIG, conn, dry_run=True)
        assert len(result.submitted) == 1
        assert result.submitted[0]["status"] == "dry_run"
        assert not result.blocked
        assert result.dry_run is True

    def test_zero_share_buy_skipped_silently(self, tmp_path):
        """propose.py writes shares=0.0 when NAV is unknown (empty portfolio) -- nothing
        to submit, and it must not show up as a spurious blocked trade either."""
        conn = store.get_conn(":memory:")
        store.init_schema(conn)
        path = self._write_proposal(
            tmp_path,
            [
                {
                    "ticker": "AAPL",
                    "action": "buy",
                    "shares": 0.0,
                    "limit_price": 100.0,
                    "lot_ids": [],
                    "sell_rule": None,
                }
            ],
        )
        result = submit_proposal(path, CONFIG, conn, dry_run=True)
        assert result.submitted == []
        assert result.blocked == []

    def test_invalid_trade_is_blocked_not_submitted(self, tmp_path):
        conn = store.get_conn(":memory:")
        store.init_schema(conn)
        path = self._write_proposal(
            tmp_path,
            [
                {
                    "ticker": "AAPL",
                    "action": "sell",
                    "shares": 1.0,
                    "limit_price": 100.0,
                    "lot_ids": [],  # missing -- must be blocked
                    "sell_rule": None,
                }
            ],
        )
        result = submit_proposal(path, CONFIG, conn, dry_run=True)
        assert result.submitted == []
        assert len(result.blocked) == 1
        assert result.blocked[0].ticker == "AAPL"


class TestAuditLog:
    def test_writes_no_api_keys(self, tmp_path, monkeypatch):
        # Patch the exact namespace `_write_audit_log` itself reads PROJECT_ROOT from,
        # not a fresh `import durable.execution.submit`: tests/test_report_safety.py
        # deletes `durable.execution.*` from sys.modules to test import isolation, which
        # (if it runs first, e.g. alphabetically before this file) makes a subsequent
        # `import durable.execution.submit as m` return a SECOND, distinct module object
        # -- monkeypatching that one would silently miss the function object already
        # bound above via `from durable.execution.submit import _write_audit_log`.
        monkeypatch.setitem(_write_audit_log.__globals__, "PROJECT_ROOT", tmp_path)
        result = SubmissionResult(
            submitted=[{"ticker": "AAPL", "status": "dry_run"}],
            blocked=[BlockedTrade(ticker="MSFT", action="sell", reason="no lot_ids")],
            dry_run=True,
        )
        out_path = _write_audit_log(tmp_path / "proposal.json", result)
        content = out_path.read_text()
        assert "AAPL" in content
        assert "MSFT" in content
        assert "ALPACA" not in content.upper() or "KEY" not in content.upper()


class TestRunCliGating:
    def test_refuses_without_i_have_read_the_proposal(self, capsys):
        code = _run_cli("some_proposal.json", i_have_read_the_proposal=False)
        assert code == 2
        assert "Refusing to run" in capsys.readouterr().out

    def test_kill_file_blocks_before_proposal_is_opened(self, tmp_path, monkeypatch, capsys):
        """Rule 6: KILL file checked before anything else -- including before the proposal
        path is even validated, so a bogus --proposal path doesn't matter here."""
        import durable.config as config_module

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_path = config_dir / "config.yaml"
        config_path.write_text("live_trading_approved: false\n")
        monkeypatch.setattr(config_module, "CONFIG_FILE", config_path)
        monkeypatch.chdir(tmp_path)  # KILL is checked relative to cwd by broker.py's default
        (tmp_path / "KILL").write_text("stop trading")

        code = _run_cli("does-not-exist.json", i_have_read_the_proposal=True)
        assert code == 1
        assert "BLOCKED" in capsys.readouterr().out
