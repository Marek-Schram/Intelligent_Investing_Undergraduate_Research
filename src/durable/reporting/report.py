"""Report orchestration module. TICKET-023.

Generates all five report types as deterministic JSON-serializable dicts.
No network calls. No imports from durable.execution.

Data source: pre-computed portfolio data passed as arguments.
available_at logic: N/A (reporting on completed data).
Spec section: docs/07 sections 1-5.

Report types:
  - quarterly: Standard quarterly performance review
  - annual: Year-end assessment with kill-criteria decision
  - adhoc: Event-triggered report (e.g., large drawdown)
  - attribution: Brinson + factor attribution breakdown
  - research: Research bulletin for paper material

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
Never imports execution/.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ReportType(Enum):
    """The five supported report types per docs/07 section 1."""

    QUARTERLY = "quarterly"
    ANNUAL = "annual"
    ADHOC = "adhoc"
    ATTRIBUTION = "attribution"
    RESEARCH = "research"


# Required fields per report type. Every generated report must contain these.
REQUIRED_FIELDS: dict[ReportType, tuple[str, ...]] = {
    ReportType.QUARTERLY: (
        "report_type",
        "period",
        "sleeve_c_return",
        "benchmark_return",
        "excess_return",
        "holdings_count",
        "turnover_pct",
        "kill_criteria",
    ),
    ReportType.ANNUAL: (
        "report_type",
        "year",
        "sleeve_c_return",
        "benchmark_return",
        "excess_return",
        "kill_criteria",
        "continue_decision",
        "since_inception_return",
    ),
    ReportType.ADHOC: (
        "report_type",
        "trigger",
        "timestamp",
        "summary",
        "affected_positions",
    ),
    ReportType.ATTRIBUTION: (
        "report_type",
        "period",
        "allocation_effect",
        "selection_effect",
        "interaction_effect",
        "total_excess",
        "factor_exposures",
    ),
    ReportType.RESEARCH: (
        "report_type",
        "period",
        "methodology_snapshot",
        "factor_ic_table",
        "pbo",
        "contamination_verdict",
        "trial_count",
    ),
}


@dataclass
class ReportValidationError(Exception):
    """Raised when report data fails validation."""

    report_type: ReportType
    missing_fields: list[str]
    message: str = field(init=False)

    def __post_init__(self) -> None:
        self.message = (
            f"Report type '{self.report_type.value}' missing required fields: "
            f"{self.missing_fields}"
        )
        super().__init__(self.message)


def _validate_required_fields(report_type: ReportType, data: dict[str, Any]) -> None:
    """Check that all required fields for the report type are present in data."""
    required = REQUIRED_FIELDS[report_type]
    # report_type is added by generate_report, so skip it in input validation
    input_required = [f for f in required if f != "report_type"]
    missing = [f for f in input_required if f not in data]
    if missing:
        raise ReportValidationError(report_type=report_type, missing_fields=missing)


def _build_quarterly(data: dict[str, Any]) -> dict[str, Any]:
    """Build a quarterly report dict."""
    return {
        "report_type": ReportType.QUARTERLY.value,
        "period": data["period"],
        "sleeve_c_return": data["sleeve_c_return"],
        "benchmark_return": data["benchmark_return"],
        "excess_return": data["excess_return"],
        "holdings_count": data["holdings_count"],
        "turnover_pct": data["turnover_pct"],
        "kill_criteria": data["kill_criteria"],
        "positions": data.get("positions", []),
        "risk_metrics": data.get("risk_metrics", {}),
        "narrative": data.get("narrative", ""),
    }


def _build_annual(data: dict[str, Any]) -> dict[str, Any]:
    """Build an annual assessment report dict."""
    return {
        "report_type": ReportType.ANNUAL.value,
        "year": data["year"],
        "sleeve_c_return": data["sleeve_c_return"],
        "benchmark_return": data["benchmark_return"],
        "excess_return": data["excess_return"],
        "kill_criteria": data["kill_criteria"],
        "continue_decision": data["continue_decision"],
        "since_inception_return": data["since_inception_return"],
        "quarterly_returns": data.get("quarterly_returns", []),
        "tax_summary": data.get("tax_summary", {}),
    }


def _build_adhoc(data: dict[str, Any]) -> dict[str, Any]:
    """Build an ad-hoc event-triggered report dict."""
    return {
        "report_type": ReportType.ADHOC.value,
        "trigger": data["trigger"],
        "timestamp": data["timestamp"],
        "summary": data["summary"],
        "affected_positions": data["affected_positions"],
        "severity": data.get("severity", "info"),
        "action_taken": data.get("action_taken", "none"),
    }


def _build_attribution(data: dict[str, Any]) -> dict[str, Any]:
    """Build an attribution report dict."""
    return {
        "report_type": ReportType.ATTRIBUTION.value,
        "period": data["period"],
        "allocation_effect": data["allocation_effect"],
        "selection_effect": data["selection_effect"],
        "interaction_effect": data["interaction_effect"],
        "total_excess": data["total_excess"],
        "factor_exposures": data["factor_exposures"],
        "position_contributions": data.get("position_contributions", []),
        "sector_breakdown": data.get("sector_breakdown", {}),
    }


def _build_research(data: dict[str, Any]) -> dict[str, Any]:
    """Build a research bulletin report dict."""
    return {
        "report_type": ReportType.RESEARCH.value,
        "period": data["period"],
        "methodology_snapshot": data["methodology_snapshot"],
        "factor_ic_table": data["factor_ic_table"],
        "pbo": data["pbo"],
        "contamination_verdict": data["contamination_verdict"],
        "trial_count": data["trial_count"],
        "disclosure": data.get("disclosure", ""),
        "seeds": data.get("seeds", []),
    }


_BUILDERS: dict[ReportType, Any] = {
    ReportType.QUARTERLY: _build_quarterly,
    ReportType.ANNUAL: _build_annual,
    ReportType.ADHOC: _build_adhoc,
    ReportType.ATTRIBUTION: _build_attribution,
    ReportType.RESEARCH: _build_research,
}


def generate_report(report_type: str | ReportType, data: dict[str, Any]) -> dict[str, Any]:
    """Generate a report dict for the given type.

    Parameters
    ----------
    report_type : str or ReportType
        One of: quarterly, annual, adhoc, attribution, research
    data : dict
        Input data containing all required fields for the report type.

    Returns
    -------
    dict
        A deterministic, JSON-serializable report dict.

    Raises
    ------
    ValueError
        If report_type is not recognized.
    ReportValidationError
        If required fields are missing from data.
    """
    if isinstance(report_type, str):
        try:
            rt = ReportType(report_type)
        except ValueError:
            valid = [t.value for t in ReportType]
            raise ValueError(
                f"Unknown report type '{report_type}'. Valid types: {valid}"
            ) from None
    else:
        rt = report_type

    _validate_required_fields(rt, data)
    builder = _BUILDERS[rt]
    return builder(data)


def report_to_json(report: dict[str, Any]) -> str:
    """Serialize a report dict to deterministic JSON.

    Sorted keys and consistent indent ensure that the same input always
    produces byte-identical output.

    Parameters
    ----------
    report : dict
        A report dict produced by generate_report.

    Returns
    -------
    str
        Deterministic JSON string.
    """
    return json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True)


def all_report_types() -> list[str]:
    """Return the list of all valid report type names."""
    return [rt.value for rt in ReportType]
