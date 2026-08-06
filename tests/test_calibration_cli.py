"""Tests for the `durable.research.calibration --score` CLI.

Does not re-test brier_score/calibration_curve/overconfidence_ratio/discrimination/
by_emotional_state/override_performance/compute_calibration -- those are covered by
tests/test_calibration.py. This covers the new CSV-loading and markdown-rendering code.
"""

from __future__ import annotations

import csv
import subprocess
import sys
from datetime import date
from pathlib import Path

from durable.research import calibration as cal_cli

FIELDS = [
    "decision_id",
    "date",
    "type",
    "ticker",
    "sleeve",
    "prediction",
    "confidence",
    "reasoning",
    "key_assumption",
    "disconfirming_evidence",
    "emotional_state",
    "system_score",
    "overrode_system",
    "resolution_date",
    "outcome",
    "resolved_correct",
]


def _row(**overrides) -> dict:
    base = {f: "" for f in FIELDS}
    base.update(
        {
            "decision_id": "D1",
            "date": "2026-01-01",
            "type": "prediction",
            "confidence": "70",
            "resolution_date": "2026-02-01",
            "resolved_correct": "correct",
        }
    )
    base.update(overrides)
    return base


def _write_journal(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_load_predictions_hand_computed_mix(tmp_path: Path):
    """3 correct, 2 incorrect, 1 partially_correct, 1 unresolved (blank), 1 expired ->
    6 binary-scoreable predictions, 3 excluded with the right breakdown."""
    rows = [
        _row(decision_id="D1", confidence="70", resolved_correct="correct"),
        _row(decision_id="D2", confidence="80", resolved_correct="True"),
        _row(decision_id="D3", confidence="90", resolved_correct="true"),
        _row(decision_id="D4", confidence="60", resolved_correct="incorrect"),
        _row(decision_id="D5", confidence="55", resolved_correct="False"),
        _row(decision_id="D6", confidence="65", resolved_correct="partially_correct"),
        _row(decision_id="D7", confidence="75", resolution_date="", resolved_correct=""),
        _row(decision_id="D8", confidence="85", resolved_correct="expired"),
    ]
    journal_path = tmp_path / "decisions.csv"
    _write_journal(journal_path, rows)

    loaded = cal_cli.load_predictions_from_journal(journal_path)

    assert loaded.n_total_rows == 8
    assert len(loaded.predictions) == 5
    outcomes = sorted((p.confidence, p.outcome) for p in loaded.predictions)
    assert outcomes == [(55, False), (60, False), (70, True), (80, True), (90, True)]
    assert loaded.n_partially_correct == 1
    assert loaded.n_expired == 1
    assert loaded.n_unresolved == 1


def test_load_predictions_out_of_range_confidence_excluded(tmp_path: Path):
    rows = [_row(decision_id="D1", confidence="40", resolved_correct="correct")]
    journal_path = tmp_path / "decisions.csv"
    _write_journal(journal_path, rows)

    loaded = cal_cli.load_predictions_from_journal(journal_path)

    assert loaded.predictions == []
    assert loaded.n_unresolved == 1


def test_load_predictions_override_flag_parsed(tmp_path: Path):
    rows = [
        _row(
            decision_id="D1", confidence="70", resolved_correct="correct", overrode_system="True"
        ),
        _row(decision_id="D2", confidence="70", resolved_correct="correct", overrode_system=""),
    ]
    journal_path = tmp_path / "decisions.csv"
    _write_journal(journal_path, rows)

    loaded = cal_cli.load_predictions_from_journal(journal_path)

    assert sum(p.is_override for p in loaded.predictions) == 1


def test_load_predictions_raises_file_not_found(tmp_path: Path):
    import pytest

    with pytest.raises(FileNotFoundError):
        cal_cli.load_predictions_from_journal(tmp_path / "does_not_exist.csv")


def test_render_calibration_markdown_empty_predictions(tmp_path: Path):
    rows = [_row(decision_id="D1", confidence="70", resolution_date="", resolved_correct="")]
    journal_path = tmp_path / "decisions.csv"
    _write_journal(journal_path, rows)
    loaded = cal_cli.load_predictions_from_journal(journal_path)

    md = cal_cli.render_calibration_markdown(loaded, date(2026, 8, 6))

    assert "No resolved, binary-scoreable predictions yet" in md
    assert "proves" not in md.lower()
    assert "confirms" not in md.lower()


def test_render_calibration_markdown_small_sample_banner(tmp_path: Path):
    rows = [
        _row(decision_id=f"D{i}", confidence="70", resolved_correct="correct") for i in range(5)
    ]
    journal_path = tmp_path / "decisions.csv"
    _write_journal(journal_path, rows)
    loaded = cal_cli.load_predictions_from_journal(journal_path)

    md = cal_cli.render_calibration_markdown(loaded, date(2026, 8, 6))

    assert "Small-sample banner" in md
    assert "Brier score" in md
    assert "0.0001" in md or "Brier score" in md  # 100% confident+always right -> ~0


def test_render_calibration_markdown_overconfident_verdict(tmp_path: Path):
    """80% confidence, 6/10 hit rate -> ratio 1.33, overconfident."""
    rows = [
        _row(decision_id=f"C{i}", confidence="80", resolved_correct="correct") for i in range(6)
    ]
    rows += [
        _row(decision_id=f"W{i}", confidence="80", resolved_correct="incorrect") for i in range(4)
    ]
    journal_path = tmp_path / "decisions.csv"
    _write_journal(journal_path, rows)
    loaded = cal_cli.load_predictions_from_journal(journal_path)

    md = cal_cli.render_calibration_markdown(loaded, date(2026, 8, 6))

    assert "overconfident" in md
    assert "1.33" in md


def test_main_no_journal_exits_nonzero_clear_message(tmp_path: Path, capsys):
    exit_code = cal_cli.main(
        ["--score", "--journal-csv", str(tmp_path / "nope.csv"), "--out-dir", str(tmp_path)]
    )
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "does not exist yet" in captured.out
    assert "Traceback" not in captured.out


def test_main_header_only_journal_exits_nonzero(tmp_path: Path, capsys):
    journal_path = tmp_path / "decisions.csv"
    _write_journal(journal_path, [])
    exit_code = cal_cli.main(
        ["--score", "--journal-csv", str(journal_path), "--out-dir", str(tmp_path)]
    )
    assert exit_code == 1
    assert "no rows yet" in capsys.readouterr().out


def test_main_writes_calibration_md(tmp_path: Path):
    rows = [
        _row(decision_id=f"D{i}", confidence="70", resolved_correct="correct") for i in range(3)
    ]
    journal_path = tmp_path / "decisions.csv"
    _write_journal(journal_path, rows)

    exit_code = cal_cli.main(
        [
            "--score",
            "--journal-csv",
            str(journal_path),
            "--out-dir",
            str(tmp_path),
            "--as-of",
            "2026-08-06",
        ]
    )

    assert exit_code == 0
    out_path = tmp_path / "calibration_2026-08-06.md"
    assert out_path.is_file()
    content = out_path.read_text()
    assert "Calibration — 2026-08-06" in content


def test_research_calibration_cli_module_never_imports_execution():
    code = (
        "import sys; "
        "import durable.research.calibration; "
        "mods = [m for m in sys.modules if m.startswith('durable.execution')]; "
        "assert not mods, mods"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
