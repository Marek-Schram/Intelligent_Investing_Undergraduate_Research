"""Tests for the `durable.research.preregister --reproduce` CLI.

Does not re-test check_harking/validate_preregistration/build_reproduction_spec/
verify_reproduction/EXPERIMENT_LOG_COLUMNS -- those are covered by tests/test_preregister.py.
This covers the new report_log.csv reader/writer and the `reproduce()` verification logic
(the lightweight design -- see the module docstring in preregister.py for why).
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

from durable.research import preregister as pr


def test_append_and_read_report_log_round_trip(tmp_path: Path):
    log_path = tmp_path / "report_log.csv"
    pr.append_report_log_row(
        log_path,
        {
            "run_id": "r1",
            "report_type": "research",
            "generated_at": "2026-08-06T10:00:00",
            "commit_hash": "abc123",
            "config_hash": "cfg1",
            "report_path": "reports/report_research_2026-08-06.json",
            "output_sha256": "deadbeef",
        },
    )
    pr.append_report_log_row(
        log_path,
        {
            "run_id": "r2",
            "report_type": "quarterly",
            "generated_at": "2026-08-06T11:00:00",
            "commit_hash": "def456",
            "config_hash": "cfg2",
            "report_path": "reports/report_quarterly_2026-08-06.json",
            "output_sha256": "feedface",
        },
    )

    rows = pr.read_report_log(log_path)

    assert len(rows) == 2
    assert rows[0]["run_id"] == "r1"
    assert rows[0]["commit_hash"] == "abc123"
    assert rows[1]["run_id"] == "r2"
    # Header matches the documented schema exactly.
    with log_path.open() as f:
        header = f.readline().strip().split(",")
    assert header == pr.REPORT_LOG_COLUMNS


def test_append_report_log_row_rejects_unknown_column(tmp_path: Path):
    with pytest.raises(ValueError, match="Unknown"):
        pr.append_report_log_row(tmp_path / "log.csv", {"not_a_real_column": "x"})


def test_read_report_log_missing_file_raises_clear_error(tmp_path: Path):
    with pytest.raises(pr.ReproduceCLIError, match="does not exist"):
        pr.read_report_log(tmp_path / "no_such_log.csv")


def test_matches_commit_handles_abbreviation():
    assert pr._matches_commit("abc123def456", "abc123")
    assert pr._matches_commit("abc123", "abc123def456")
    assert not pr._matches_commit("abc123", "xyz999")
    assert not pr._matches_commit("", "abc123")


def test_reproduce_missing_log_returns_1(tmp_path: Path, capsys):
    exit_code = pr.reproduce("abc123", tmp_path / "report_log.csv")
    assert exit_code == 1
    assert "does not exist" in capsys.readouterr().out


def test_reproduce_no_matching_commit_returns_1(tmp_path: Path, capsys):
    report_path = tmp_path / "reports" / "report_research_2026-08-06.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text('{"a": 1}')
    log_path = tmp_path / "report_log.csv"
    pr.append_report_log_row(
        log_path,
        {
            "run_id": "r1",
            "commit_hash": "aaa111",
            "report_path": str(report_path),
            "output_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        },
    )

    exit_code = pr.reproduce("zzz999", log_path)

    assert exit_code == 1
    assert "No run recorded at commit" in capsys.readouterr().out


def test_reproduce_pass_when_head_matches_and_hash_matches(tmp_path: Path, monkeypatch, capsys):
    report_path = tmp_path / "reports" / "report_research_2026-08-06.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text('{"a": 1}')
    log_path = tmp_path / "report_log.csv"
    pr.append_report_log_row(
        log_path,
        {
            "run_id": "r1",
            "commit_hash": "abc123",
            "report_path": str(report_path),
            "output_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        },
    )
    monkeypatch.setattr(pr, "_current_git_commit", lambda: "abc123")

    exit_code = pr.reproduce("abc123", log_path)

    assert exit_code == 0
    assert "PASS r1" in capsys.readouterr().out


def test_reproduce_fail_on_hash_mismatch(tmp_path: Path, monkeypatch, capsys):
    report_path = tmp_path / "reports" / "report_research_2026-08-06.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text('{"a": 1}')
    log_path = tmp_path / "report_log.csv"
    pr.append_report_log_row(
        log_path,
        {
            "run_id": "r1",
            "commit_hash": "abc123",
            "report_path": str(report_path),
            "output_sha256": "0" * 64,  # deliberately wrong
        },
    )
    monkeypatch.setattr(pr, "_current_git_commit", lambda: "abc123")

    exit_code = pr.reproduce("abc123", log_path)

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "FAIL r1" in out
    assert "hash mismatch" in out


def test_reproduce_unverified_when_head_does_not_match_requested_commit(
    tmp_path: Path, monkeypatch, capsys
):
    """The lightweight design's core honesty check: a matching file hash under a mismatched
    checkout is reported UNVERIFIED, never PASS."""
    report_path = tmp_path / "reports" / "report_research_2026-08-06.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text('{"a": 1}')
    log_path = tmp_path / "report_log.csv"
    pr.append_report_log_row(
        log_path,
        {
            "run_id": "r1",
            "commit_hash": "abc123",
            "report_path": str(report_path),
            "output_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        },
    )
    monkeypatch.setattr(pr, "_current_git_commit", lambda: "totally-different-commit")

    exit_code = pr.reproduce("abc123", log_path)

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "UNVERIFIED r1" in out
    # The word "PASS" legitimately appears in the warning's own explanatory prose (see
    # assertion above) -- what must never appear is a *status line* reporting PASS.
    assert "PASS r1" not in out


def test_reproduce_fail_when_recorded_file_missing(tmp_path: Path, monkeypatch, capsys):
    log_path = tmp_path / "report_log.csv"
    pr.append_report_log_row(
        log_path,
        {
            "run_id": "r1",
            "commit_hash": "abc123",
            "report_path": str(tmp_path / "reports" / "gone.json"),
            "output_sha256": "irrelevant",
        },
    )
    monkeypatch.setattr(pr, "_current_git_commit", lambda: "abc123")

    exit_code = pr.reproduce("abc123", log_path)

    assert exit_code == 1
    assert "recorded output file missing" in capsys.readouterr().out


def test_main_reproduce_flag_dispatches(tmp_path: Path, monkeypatch, capsys):
    report_path = tmp_path / "reports" / "report_research_2026-08-06.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text('{"a": 1}')
    log_path = tmp_path / "report_log.csv"
    pr.append_report_log_row(
        log_path,
        {
            "run_id": "r1",
            "commit_hash": "abc123",
            "report_path": str(report_path),
            "output_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        },
    )
    monkeypatch.setattr(pr, "_current_git_commit", lambda: "abc123")

    exit_code = pr.main(["--reproduce", "abc123", "--report-log", str(log_path)])

    assert exit_code == 0
    assert "PASS r1" in capsys.readouterr().out


def test_research_preregister_cli_module_never_imports_execution():
    code = (
        "import sys; "
        "import durable.research.preregister; "
        "mods = [m for m in sys.modules if m.startswith('durable.execution')]; "
        "assert not mods, mods"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
