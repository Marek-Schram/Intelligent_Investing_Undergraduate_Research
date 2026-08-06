"""Tests for the ingestion CLI orchestrator (data/ingest.py).

These test the new orchestration logic only (credential gating, per-step failure
isolation, report formatting/writing, argument validation) -- not the pure functions in
prices.py/sec.py/macro.py/universe.py, which already have their own tests. No test in this
file makes a network call: every credential-gated step fails deterministically because the
env mapping supplied is empty, and the network-dependent-but-keyless factors step is
monkeypatched out.
"""

from __future__ import annotations

import json

import pytest

from durable.data import ingest
from durable.data.ingest import (
    MissingCredentialError,
    StepResult,
    _require_env,
    format_report,
    main,
    run_ingest,
    write_report_json,
)
from durable.data.store import get_conn, init_schema


@pytest.fixture
def conn():
    c = get_conn(":memory:")
    init_schema(c)
    return c


class TestRequireEnv:
    def test_missing_var_raises_with_var_name_and_feature(self):
        with pytest.raises(MissingCredentialError) as exc_info:
            _require_env({}, "FRED_API_KEY", "macro series ingestion (FRED)")
        msg = str(exc_info.value)
        assert "FRED_API_KEY" in msg
        assert "macro series ingestion (FRED)" in msg
        assert ".env" in msg

    def test_empty_string_treated_as_missing(self):
        with pytest.raises(MissingCredentialError):
            _require_env({"FRED_API_KEY": ""}, "FRED_API_KEY", "macro")

    def test_present_var_returned(self):
        assert _require_env({"FRED_API_KEY": "abc123"}, "FRED_API_KEY", "macro") == "abc123"


class TestRunIngestNoCredentials:
    """Hand-computed fixture: an empty env (matches this repo's empty .env) must fail every
    credential-gated step with a specific, actionable message and must never raise."""

    def test_all_credentialed_steps_report_missing_key(self, conn, monkeypatch):
        # Keep the factors step (no credential, real network) out of this test.
        monkeypatch.setattr(ingest.macro, "ingest_factors", lambda conn: "stub-factors-snapshot")

        from datetime import date

        results = run_ingest(
            ["AAPL"],
            conn,
            env={},
            price_history_start=date(2020, 1, 1),
            universe_as_of=date(2024, 1, 1),
        )

        by_name = {r.name: r for r in results}

        assert by_name["prices"].ok is False
        assert "ALPACA_PAPER_KEY_ID" in by_name["prices"].detail

        assert by_name["fundamentals"].ok is False
        assert "EDGAR_IDENTITY" in by_name["fundamentals"].detail

        assert by_name["macro"].ok is False
        assert "FRED_API_KEY" in by_name["macro"].detail

        # Factors was stubbed out -- succeeds without touching the network.
        assert by_name["factors"].ok is True

        # Universe build succeeds trivially: no fundamentals were ingested, so it is an
        # empty-but-valid universe, not an error.
        assert by_name["universe"].ok is True
        assert "0 tickers eligible" in by_name["universe"].detail

    def test_never_raises_even_though_every_credentialed_step_fails(self, conn, monkeypatch):
        monkeypatch.setattr(ingest.macro, "ingest_factors", lambda conn: "stub")
        from datetime import date

        # Must not raise -- this is the whole point of the orchestrator.
        results = run_ingest(
            ["AAPL", "MSFT"],
            conn,
            env={},
            price_history_start=date(2020, 1, 1),
            universe_as_of=date(2024, 1, 1),
        )
        assert len(results) >= 4
        assert all(isinstance(r, StepResult) for r in results)


class TestFailureIsolation:
    """One ticker's ingestion failure must not stop the others (or the other sources)."""

    def test_per_ticker_prices_failure_does_not_stop_other_tickers(self, conn, monkeypatch):
        from datetime import date

        calls = []

        def fake_client(key, secret):
            return object()

        def fake_ingest_daily_bars(conn, client, ticker, start, end=None, snapshot_id=None):
            calls.append(ticker)
            if ticker == "BAD":
                raise ValueError("no price data returned")
            return f"snap-{ticker}"

        monkeypatch.setattr(ingest.prices, "get_price_client", fake_client)
        monkeypatch.setattr(ingest.prices, "ingest_daily_bars", fake_ingest_daily_bars)
        monkeypatch.setattr(ingest.macro, "ingest_factors", lambda conn: "stub")

        results = run_ingest(
            ["BAD", "AAPL"],
            conn,
            env={"ALPACA_PAPER_KEY_ID": "k", "ALPACA_PAPER_SECRET_KEY": "s"},
            price_history_start=date(2020, 1, 1),
            universe_as_of=date(2024, 1, 1),
        )

        assert calls == ["BAD", "AAPL"]  # both attempted
        by_name = {r.name: r for r in results}
        assert by_name["prices:BAD"].ok is False
        assert "no price data returned" in by_name["prices:BAD"].detail
        assert by_name["prices:AAPL"].ok is True


class TestFormatReport:
    def test_reports_ok_and_fail_counts(self):
        results = [
            StepResult("prices:AAPL", True, "snapshot=x"),
            StepResult("macro", False, "FRED_API_KEY is not set"),
        ]
        text = format_report(results)
        assert "[OK  ] prices:AAPL: snapshot=x" in text
        assert "[FAIL] macro: FRED_API_KEY is not set" in text
        assert "1 succeeded, 1 failed out of 2 step(s)." in text


class TestWriteReportJson:
    def test_writes_valid_json_with_expected_shape(self, tmp_path):
        results = [
            StepResult("prices:AAPL", True, "snapshot=x"),
            StepResult("macro", False, "FRED_API_KEY is not set"),
        ]
        out_path = write_report_json(results, tmp_path)

        assert out_path.exists()
        assert out_path.parent == tmp_path
        assert out_path.name.startswith("ingest_") and out_path.name.endswith(".json")

        payload = json.loads(out_path.read_text())
        assert payload["n_ok"] == 1
        assert payload["n_failed"] == 1
        assert len(payload["steps"]) == 2
        assert payload["steps"][0] == {"name": "prices:AAPL", "ok": True, "detail": "snapshot=x"}


class TestMainArgumentValidation:
    def test_requires_all_or_tickers(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "--all" in captured.err or "--all" in captured.out


class TestMainEndToEnd:
    """main() wired end to end against a tmp DuckDB file, with every credentialed source
    failing (empty environment) and the network-dependent factors step stubbed out."""

    def test_exit_code_1_when_every_source_fails(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(ingest.macro, "ingest_factors", lambda conn: "stub")
        # main() calls load_dotenv(), which never overrides a key that is already present
        # in os.environ (even an empty one) -- so setenv("") here, not delenv(), is what
        # actually blocks a real local .env from leaking real credentials into this test.
        monkeypatch.setenv("ALPACA_PAPER_KEY_ID", "")
        monkeypatch.setenv("ALPACA_PAPER_SECRET_KEY", "")
        monkeypatch.setenv("EDGAR_IDENTITY", "")
        monkeypatch.setenv("FRED_API_KEY", "")

        db_path = tmp_path / "test.duckdb"
        out_dir = tmp_path / "reports"

        exit_code = main(
            [
                "--tickers",
                "AAPL",
                "--db-path",
                str(db_path),
                "--out-dir",
                str(out_dir),
                "--as-of",
                "2024-01-01",
            ]
        )

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Ingest report:" in captured.out
        assert "Report written to" in captured.out

        report_files = list(out_dir.glob("ingest_*.json"))
        assert len(report_files) == 1
        payload = json.loads(report_files[0].read_text())
        assert payload["n_failed"] >= 3  # prices, fundamentals, macro all fail
