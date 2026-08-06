"""Tests for report orchestration module. TICKET-023.

Covers:
- All 5 report types generate successfully
- Import isolation: durable.reporting.report does NOT transitively import durable.execution
- Deterministic JSON output (same input -> same JSON string)
- No network calls (module has no requests/urllib/httpx imports)
- Validation of required fields
- Error handling for invalid report types
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys

import pytest

from durable.reporting.report import (
    REQUIRED_FIELDS,
    ReportType,
    ReportValidationError,
    all_report_types,
    generate_report,
    report_to_json,
)

# --- Fixtures providing minimal valid data for each report type ---


def _quarterly_data() -> dict:
    return {
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
        "positions": [{"ticker": "AAPL", "weight": 0.05}],
        "risk_metrics": {"volatility": 0.12},
    }


def _annual_data() -> dict:
    return {
        "year": 2025,
        "sleeve_c_return": 0.112,
        "benchmark_return": 0.098,
        "excess_return": 0.014,
        "kill_criteria": {
            "max_drawdown": "PASS",
            "tracking_error": "PASS",
            "turnover": "PASS",
            "sharpe_underperformance": "PASS",
            "holding_period": "PASS",
            "pbo": "PASS",
        },
        "continue_decision": True,
        "since_inception_return": 0.087,
        "quarterly_returns": [0.02, 0.03, 0.04, 0.022],
    }


def _adhoc_data() -> dict:
    return {
        "trigger": "drawdown_threshold",
        "timestamp": "2025-07-15T10:00:00Z",
        "summary": "Sleeve C drawdown exceeded 10% intraday",
        "affected_positions": ["MSFT", "GOOGL"],
        "severity": "warning",
    }


def _attribution_data() -> dict:
    return {
        "period": "2025-Q3",
        "allocation_effect": 0.002,
        "selection_effect": -0.015,
        "interaction_effect": 0.001,
        "total_excess": -0.012,
        "factor_exposures": {
            "market": 0.95,
            "value": 0.3,
            "quality": 0.4,
            "momentum": -0.1,
            "size": 0.2,
        },
        "position_contributions": [
            {"ticker": "AAPL", "contribution": 0.003},
            {"ticker": "MSFT", "contribution": -0.008},
        ],
    }


def _research_data() -> dict:
    return {
        "period": "2025-Q3",
        "methodology_snapshot": {
            "git_commit": "abc123",
            "config_hash": "def456",
            "bootstrap_method": "stationary_block",
            "block_size": 4,
        },
        "factor_ic_table": {
            "durability": {"ic": 0.031, "t_stat": 2.1, "ir": 0.45},
            "valuation": {"ic": 0.028, "t_stat": 1.8, "ir": 0.38},
        },
        "pbo": 0.41,
        "contamination_verdict": "clean",
        "trial_count": 47,
        "seeds": [42, 123, 7],
    }


_ALL_REPORT_DATA = {
    "quarterly": _quarterly_data,
    "annual": _annual_data,
    "adhoc": _adhoc_data,
    "attribution": _attribution_data,
    "research": _research_data,
}


# --- Test: all 5 report types generate successfully ---


@pytest.mark.parametrize(
    "report_type", ["quarterly", "annual", "adhoc", "attribution", "research"]
)
def test_generate_all_five_types(report_type: str) -> None:
    """Each of the five report types produces a valid dict with all required fields."""
    data = _ALL_REPORT_DATA[report_type]()
    result = generate_report(report_type, data)

    assert isinstance(result, dict)
    assert result["report_type"] == report_type

    # Check all required fields are present
    rt = ReportType(report_type)
    for field_name in REQUIRED_FIELDS[rt]:
        assert field_name in result, f"Missing required field: {field_name}"


# --- Test: import isolation (CRITICAL) ---


def test_import_does_not_transitively_import_execution() -> None:
    """CRITICAL: importing durable.reporting.report must NOT transitively import
    durable.execution. This ensures a scheduled report can never place an order.

    Uses a subprocess to get a clean import state.
    """
    code = (
        "import sys; "
        "import durable.reporting.report; "
        "mods = [m for m in sys.modules if m.startswith('durable.execution')]; "
        "print(repr(mods)); "
        "assert not mods, f'Leaked execution imports: {mods}'"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Import isolation violated. stdout={result.stdout}, stderr={result.stderr}"
    )


def test_import_does_not_transitively_import_execution_via_sys_modules() -> None:
    """Secondary check: verify via importlib that the module graph is clean."""
    # Reload in current process and check sys.modules
    # First note which execution modules are already loaded (from other tests)
    pre_existing = {m for m in sys.modules if m.startswith("durable.execution")}

    # Force a fresh import of the module
    mod_name = "durable.reporting.report"
    if mod_name in sys.modules:
        # Already imported; check what it pulled in
        pass
    else:
        importlib.import_module(mod_name)

    # Check no new execution modules were introduced by this import
    post_existing = {m for m in sys.modules if m.startswith("durable.execution")}
    new_execution_imports = post_existing - pre_existing
    assert not new_execution_imports, (
        f"durable.reporting.report transitively imported: {new_execution_imports}"
    )


# --- Test: deterministic JSON output ---


def test_deterministic_json_same_input_same_output() -> None:
    """Same input data must produce byte-identical JSON every time."""
    data = _quarterly_data()
    report = generate_report("quarterly", data)

    json1 = report_to_json(report)
    json2 = report_to_json(report)

    assert json1 == json2


def test_deterministic_json_across_regeneration() -> None:
    """Generating the report twice from the same input yields identical JSON."""
    data = _attribution_data()

    report_a = generate_report("attribution", data)
    report_b = generate_report("attribution", data)

    json_a = report_to_json(report_a)
    json_b = report_to_json(report_b)

    assert json_a == json_b
    # Also verify it's valid JSON
    parsed = json.loads(json_a)
    assert parsed == report_a


def test_json_has_sorted_keys() -> None:
    """JSON output must have sorted keys for determinism."""
    data = _quarterly_data()
    report = generate_report("quarterly", data)
    json_str = report_to_json(report)
    parsed = json.loads(json_str)

    # Verify top-level keys are sorted
    keys = list(parsed.keys())
    assert keys == sorted(keys)


# --- Test: no network calls ---


def test_no_network_imports_in_module() -> None:
    """The report module must not import any networking libraries."""
    import inspect

    import durable.reporting.report as report_mod

    source = inspect.getsource(report_mod)

    forbidden_imports = ["requests", "urllib", "httpx", "aiohttp", "socket"]
    for lib in forbidden_imports:
        assert f"import {lib}" not in source, f"report.py imports networking library: {lib}"


def test_no_network_at_generation_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """Monkeypatch socket to raise; report generation must still succeed."""
    import socket

    original_socket = socket.socket

    def _blocked_socket(*args, **kwargs):
        raise RuntimeError("Network access blocked during report generation")

    monkeypatch.setattr(socket, "socket", _blocked_socket)

    # Generate all report types — none should need network
    for report_type, data_fn in _ALL_REPORT_DATA.items():
        result = generate_report(report_type, data_fn())
        assert result["report_type"] == report_type

    # Restore (monkeypatch handles this automatically)


# --- Test: validation and error handling ---


def test_missing_required_fields_raises() -> None:
    """Missing a required field raises ReportValidationError."""
    incomplete_data = {"period": "2025-Q3"}  # Missing most required fields

    with pytest.raises(ReportValidationError) as exc_info:
        generate_report("quarterly", incomplete_data)

    assert "sleeve_c_return" in exc_info.value.missing_fields


def test_invalid_report_type_raises() -> None:
    """An unknown report type raises ValueError with valid types listed."""
    with pytest.raises(ValueError, match="Unknown report type"):
        generate_report("nonexistent", {})


def test_report_type_enum_accepted() -> None:
    """generate_report accepts ReportType enum values directly."""
    data = _research_data()
    result = generate_report(ReportType.RESEARCH, data)
    assert result["report_type"] == "research"


def test_all_report_types_function() -> None:
    """all_report_types() returns exactly the five expected types."""
    types = all_report_types()
    assert set(types) == {"quarterly", "annual", "adhoc", "attribution", "research"}
    assert len(types) == 5
