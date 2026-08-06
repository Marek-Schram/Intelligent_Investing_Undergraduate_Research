"""Tests for the firewall CLI (`--audit`) added to data/firewall.py. TICKET-042.

Only the NEW CLI-level orchestration is tested here (report formatting/writing, argument
validation, the audit-then-report pipeline). The audit() sweep logic itself is untouched
and already covered by tests/test_firewall.py.
"""

from __future__ import annotations

import json
from datetime import date, datetime

import pandas as pd
import pytest

from durable.data.firewall import format_audit_report, main, write_audit_report_json
from durable.data.store import get_conn, init_schema, write_snapshot


class TestFormatAuditReport:
    def test_empty_violations_reports_pass(self):
        violations = pd.DataFrame(
            columns=["table_name", "as_of", "n_rows", "detail", "violation_type"]
        )
        text = format_audit_report(violations, pd.Timestamp("2024-06-01"))
        assert "PASS" in text
        assert "FAIL" not in text

    def test_nonempty_violations_reports_fail_with_detail(self):
        violations = pd.DataFrame(
            [
                {
                    "table_name": "bars_daily",
                    "as_of": pd.Timestamp("2024-06-01"),
                    "n_rows": 3,
                    "detail": "3 rows have available_at > 2024-06-01",
                    "violation_type": "future_data",
                }
            ]
        )
        text = format_audit_report(violations, pd.Timestamp("2024-06-01"))
        assert "FAIL" in text
        assert "bars_daily" in text
        assert "3 row(s)" in text
        assert "future_data" in text


class TestWriteAuditReportJson:
    def test_writes_pass_report(self, tmp_path):
        violations = pd.DataFrame(
            columns=["table_name", "as_of", "n_rows", "detail", "violation_type"]
        )
        out_path = write_audit_report_json(violations, pd.Timestamp("2024-06-01"), tmp_path)

        assert out_path.exists()
        assert out_path.name.startswith("leakage_audit_") and out_path.name.endswith(".json")
        payload = json.loads(out_path.read_text())
        assert payload["pass"] is True
        assert payload["n_violations"] == 0
        assert payload["violations"] == []

    def test_writes_fail_report_with_violation_rows(self, tmp_path):
        violations = pd.DataFrame(
            [
                {
                    "table_name": "short_interest",
                    "as_of": pd.Timestamp("2024-06-01"),
                    "n_rows": 5,
                    "detail": "lag too short",
                    "violation_type": "lag_violation",
                }
            ]
        )
        out_path = write_audit_report_json(violations, pd.Timestamp("2024-06-01"), tmp_path)
        payload = json.loads(out_path.read_text())
        assert payload["pass"] is False
        assert payload["n_violations"] == 1
        assert payload["violations"][0]["table_name"] == "short_interest"


class TestMainArgumentValidation:
    def test_requires_audit_flag(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 2


class TestMainEndToEnd:
    def test_clean_empty_store_passes(self, tmp_path, capsys):
        db_path = tmp_path / "clean.duckdb"
        out_dir = tmp_path / "reports"

        exit_code = main(
            [
                "--audit",
                "--db-path",
                str(db_path),
                "--out-dir",
                str(out_dir),
                "--as-of",
                "2024-06-15",
            ]
        )

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "PASS" in captured.out
        assert "Report written to" in captured.out
        assert len(list(out_dir.glob("leakage_audit_*.json"))) == 1

    def test_future_dated_row_fails_the_audit(self, tmp_path, capsys):
        """Hand-computed fixture: seed one bars_daily row with available_at in the future
        relative to --as-of, then confirm the CLI reports FAIL and exits non-zero."""
        db_path = tmp_path / "dirty.duckdb"
        out_dir = tmp_path / "reports"

        seed_conn = get_conn(db_path)
        init_schema(seed_conn)
        df = pd.DataFrame(
            [
                {
                    "ticker": "AAPL",
                    "dt": date(2030, 1, 2),
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "volume": 1_000_000,
                    "available_at": datetime(2030, 1, 2, 16, 0, 0),
                }
            ]
        )
        write_snapshot(seed_conn, "bars_daily", df, snapshot_id="test-future-bar")
        seed_conn.close()

        exit_code = main(
            [
                "--audit",
                "--db-path",
                str(db_path),
                "--out-dir",
                str(out_dir),
                "--as-of",
                "2025-01-01",
            ]
        )

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "FAIL" in captured.out
        assert "bars_daily" in captured.out

        report_files = list(out_dir.glob("leakage_audit_*.json"))
        assert len(report_files) == 1
        payload = json.loads(report_files[0].read_text())
        assert payload["pass"] is False
        assert payload["n_violations"] == 1
