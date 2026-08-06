"""Tests for the `durable.reporting.report` CLI: data assembly + orchestration.

Does NOT re-test generate_report()/report_to_json()/performance.py/attribution.py/
inference.py/narrative.py themselves -- those are covered by tests/test_report.py and
their own test files. This covers the new CLI-level code: locating/parsing backtest
output, summarizing the factor_ic table, the DataUnavailableError messages, --data-json
passthrough, the report_log.csv writer, and the research-export bundle wiring.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from durable.data import store
from durable.reporting import report as report_cli


def test_quarter_label_hand_computed():
    from datetime import date

    assert report_cli._quarter_label(date(2026, 1, 15)) == "2026-Q1"
    assert report_cli._quarter_label(date(2026, 3, 31)) == "2026-Q1"
    assert report_cli._quarter_label(date(2026, 4, 1)) == "2026-Q2"
    assert report_cli._quarter_label(date(2026, 8, 6)) == "2026-Q3"
    assert report_cli._quarter_label(date(2026, 12, 31)) == "2026-Q4"


def test_find_latest_backtest_json_picks_newest(tmp_path: Path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    older = reports_dir / "backtest_design_2025-01-01.json"
    newer = reports_dir / "backtest_design_2025-06-01.json"
    older.write_text("{}")
    newer.write_text("{}")
    # Force distinct mtimes regardless of filesystem clock resolution.
    import os
    import time

    os.utime(older, (time.time() - 100, time.time() - 100))
    os.utime(newer, (time.time(), time.time()))

    found = report_cli._find_latest_backtest_json(reports_dir, segment=None)
    assert found == newer


def test_find_latest_backtest_json_none_when_missing(tmp_path: Path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    assert report_cli._find_latest_backtest_json(reports_dir, segment=None) is None


def test_find_latest_backtest_json_filters_by_segment(tmp_path: Path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "backtest_design_2025-01-01.json").write_text("{}")
    (reports_dir / "backtest_holdout_2025-02-01.json").write_text("{}")

    found = report_cli._find_latest_backtest_json(reports_dir, segment="holdout")
    assert found is not None
    assert found.name == "backtest_holdout_2025-02-01.json"


def test_load_factor_ic_table_hand_computed():
    """factor='durability', ic=[0.02, 0.04, 0.03] -> mean=0.03, sample stdev=0.01,
    t = 0.03 / (0.01/sqrt(3)) = 0.03 / 0.005773... = 5.196..."""
    conn = store.get_conn(":memory:")
    store.init_schema(conn)
    df = pd.DataFrame(
        {
            "as_of": pd.to_datetime(["2024-01-01", "2024-04-01", "2024-07-01"]).date,
            "factor": ["durability", "durability", "durability"],
            "horizon_q": [4, 4, 4],
            "ic": [0.02, 0.04, 0.03],
            "n_names": [50, 50, 50],
        }
    )
    store.write_snapshot(conn, "factor_ic", df, "snap1")

    table = report_cli._load_factor_ic_table(conn)

    assert set(table.keys()) == {"durability"}
    assert table["durability"]["ic"] == pytest.approx(0.03, rel=1e-9)
    assert table["durability"]["t_stat"] == pytest.approx(5.196152, rel=1e-4)
    assert table["durability"]["n_periods"] == 3


def test_load_factor_ic_table_empty_when_no_rows():
    conn = store.get_conn(":memory:")
    store.init_schema(conn)
    assert report_cli._load_factor_ic_table(conn) == {}


def test_assemble_performance_based_data_raises_when_no_backtest(tmp_path: Path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()

    class _Args:
        segment = None

    from durable.reporting.report import ReportType

    with pytest.raises(report_cli.DataUnavailableError, match="No backtest output found"):
        report_cli._assemble_performance_based_data(
            "quarterly", ReportType.QUARTERLY, _Args(), reports_dir
        )


def test_assemble_performance_based_data_lists_missing_fields(tmp_path: Path):
    """Backtest output exists and is used for real numbers in the message, but the
    quarterly-specific fields with no data source anywhere are named explicitly."""
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "backtest_design_2025-01-01.json").write_text(
        json.dumps({"cagr": 0.081, "period_returns": [0.01, -0.02, 0.03, 0.015]})
    )

    class _Args:
        segment = None

    from durable.reporting.report import ReportType

    with pytest.raises(report_cli.DataUnavailableError) as exc_info:
        report_cli._assemble_performance_based_data(
            "quarterly", ReportType.QUARTERLY, _Args(), reports_dir
        )
    msg = str(exc_info.value)
    assert "benchmark_return" in msg
    assert "kill_criteria" in msg
    assert "holdings_count" in msg
    assert "turnover_pct" in msg
    assert "8.10%" in msg  # real cagr from the fixture, not fabricated


def test_assemble_performance_based_data_raises_on_empty_period_returns(tmp_path: Path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "backtest_design_2025-01-01.json").write_text(
        json.dumps({"cagr": 0.0, "period_returns": []})
    )

    class _Args:
        segment = None

    from durable.reporting.report import ReportType

    with pytest.raises(report_cli.DataUnavailableError, match="no period_returns"):
        report_cli._assemble_performance_based_data(
            "quarterly", ReportType.QUARTERLY, _Args(), reports_dir
        )


def test_assemble_data_with_data_json_passthrough(tmp_path: Path):
    data = {
        "period": "2025-Q3",
        "sleeve_c_return": 0.031,
        "benchmark_return": 0.044,
        "excess_return": -0.013,
        "holdings_count": 18,
        "turnover_pct": 22.0,
        "kill_criteria": {k: "PASS" for k in range(6)},
    }
    data_path = tmp_path / "data.json"
    data_path.write_text(json.dumps(data))

    class _Args:
        data_json = str(data_path)

    from durable.reporting.report import ReportType

    result = report_cli._assemble_data(
        "quarterly", ReportType.QUARTERLY, _Args(), tmp_path, tmp_path / "nonexistent.duckdb"
    )
    # JSON object keys are always strings, so a round trip through the file turns
    # kill_criteria's int keys into strings -- compare against the same round trip rather
    # than the pre-serialization dict.
    assert result == json.loads(json.dumps(data))


def test_assemble_data_data_json_missing_path_raises(tmp_path: Path):
    class _Args:
        data_json = str(tmp_path / "does_not_exist.json")

    from durable.reporting.report import ReportType

    with pytest.raises(report_cli.DataUnavailableError, match="not found"):
        report_cli._assemble_data(
            "quarterly", ReportType.QUARTERLY, _Args(), tmp_path, tmp_path / "x.duckdb"
        )


def test_assemble_research_data_no_db_no_factor_ic(tmp_path: Path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "experiment_log.csv").write_text("run_id,date\n")

    class _Args:
        as_of = "2026-08-06"

    db_path = tmp_path / "does_not_exist.duckdb"
    data = report_cli._assemble_research_data(_Args(), reports_dir, db_path)

    assert data["period"] == "2026-Q3"
    assert data["factor_ic_table"] == {}
    assert data["pbo"] is None
    assert data["contamination_verdict"] == "not_yet_assessed"
    assert data["trial_count"] >= 1
    assert "factor_ic_table is empty" in data["disclosure"]
    assert "pbo is null" in data["disclosure"]


def test_assemble_research_data_raises_when_experiment_log_missing(tmp_path: Path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()  # no experiment_log.csv written

    class _Args:
        as_of = None

    with pytest.raises(report_cli.DataUnavailableError, match="experiment_log"):
        report_cli._assemble_research_data(_Args(), reports_dir, tmp_path / "x.duckdb")


# --- main() end-to-end ---


def test_main_writes_data_json_report(tmp_path: Path, capsys):
    data = {
        "period": "2025-Q3",
        "sleeve_c_return": 0.031,
        "benchmark_return": 0.044,
        "excess_return": -0.013,
        "holdings_count": 18,
        "turnover_pct": 22.0,
        "kill_criteria": {
            "max_drawdown": "PASS",
            "tracking_error": "PASS",
            "turnover": "PASS",
            "sharpe_underperformance": "PASS",
            "holding_period": "PASS",
            "pbo": "PASS",
        },
    }
    data_path = tmp_path / "data.json"
    data_path.write_text(json.dumps(data))
    reports_dir = tmp_path / "reports"

    exit_code = report_cli.main(
        [
            "--type",
            "quarterly",
            "--data-json",
            str(data_path),
            "--out-dir",
            str(reports_dir),
            "--as-of",
            "2025-09-30",
        ]
    )

    assert exit_code == 0
    out_path = reports_dir / "report_quarterly_2025-09-30.json"
    assert out_path.is_file()
    written = json.loads(out_path.read_text())
    assert written["report_type"] == "quarterly"
    assert written["sleeve_c_return"] == 0.031

    # report_log.csv was appended with a real sha256 that matches the file on disk.
    log_rows = list(__import__("csv").DictReader((reports_dir / "report_log.csv").open()))
    assert len(log_rows) == 1
    import hashlib

    assert log_rows[0]["output_sha256"] == hashlib.sha256(out_path.read_bytes()).hexdigest()
    assert log_rows[0]["report_path"].endswith("report_quarterly_2025-09-30.json")
    assert log_rows[0]["report_type"] == "quarterly"
    assert log_rows[0]["commit_hash"]  # non-empty; "unknown" is acceptable outside a repo


def test_main_exits_nonzero_with_clear_message_when_no_backtest_data(tmp_path: Path, capsys):
    reports_dir = tmp_path / "reports"

    exit_code = report_cli.main(["--type", "quarterly", "--out-dir", str(reports_dir)])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "No backtest output found" in captured.out
    # No traceback: only our own message was printed.
    assert "Traceback" not in captured.out


def test_main_export_only_valid_with_research_type(tmp_path: Path):
    reports_dir = tmp_path / "reports"
    with pytest.raises(SystemExit):
        report_cli.main(["--type", "quarterly", "--export", "--out-dir", str(reports_dir)])


def test_main_research_type_end_to_end(tmp_path: Path):
    """No DB, no factor_ic, but a real experiment_log.csv -- the research report should
    still generate (honestly, with null pbo / not_yet_assessed contamination)."""
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "experiment_log.csv").write_text("run_id,date\n")

    exit_code = report_cli.main(
        [
            "--type",
            "research",
            "--out-dir",
            str(reports_dir),
            "--db-path",
            str(tmp_path / "nope.duckdb"),
            "--as-of",
            "2026-08-06",
        ]
    )

    assert exit_code == 0
    out_path = reports_dir / "report_research_2026-08-06.json"
    written = json.loads(out_path.read_text())
    assert written["report_type"] == "research"
    assert written["pbo"] is None
    assert written["contamination_verdict"] == "not_yet_assessed"


def test_main_research_export_bundle(tmp_path: Path, monkeypatch):
    """--export writes the research/export_<date>/ bundle with a real 300dpi figure."""
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "experiment_log.csv").write_text("run_id,date\n")

    # research export bundle is written under PROJECT_ROOT/research; redirect PROJECT_ROOT
    # for this test so nothing lands in the real repo.
    monkeypatch.setattr(report_cli, "PROJECT_ROOT", tmp_path)

    exit_code = report_cli.main(
        [
            "--type",
            "research",
            "--export",
            "--out-dir",
            str(reports_dir),
            "--db-path",
            str(tmp_path / "nope.duckdb"),
            "--as-of",
            "2026-08-06",
        ]
    )

    assert exit_code == 0
    export_dir = tmp_path / "research" / "export_2026-08-06"
    assert (export_dir / "metrics.json").is_file()
    assert (export_dir / "factor_ic.csv").is_file()
    assert (export_dir / "tables" / "factor_ic.tex").is_file()
    assert (export_dir / "figures" / "factor_ic.png").is_file()
    assert (export_dir / "methodology.md").is_file()
    assert (export_dir / "appendix.md").is_file()

    # Real 300dpi PNG: check the DPI metadata written by matplotlib.
    from PIL import Image

    with Image.open(export_dir / "figures" / "factor_ic.png") as im:
        dpi = im.info.get("dpi", (0, 0))
        assert round(dpi[0]) == 300


def test_reporting_report_cli_module_never_imports_execution():
    code = (
        "import sys; "
        "import durable.reporting.report; "
        "mods = [m for m in sys.modules if m.startswith('durable.execution')]; "
        "assert not mods, mods"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
