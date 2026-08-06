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

PURE FUNCTIONS ONLY (up to the CLI section at the bottom): no I/O, network, wall-clock,
or config lookups. Never imports execution/. The CLI section does real file/DuckDB I/O to
assemble the `data` dict these functions need; it is kept clearly separate so the
generate_report()/report_to_json() contract above stays pure and unit-testable with plain
dicts, per tests/test_report.py.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from pathlib import Path
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


# ---------------------------------------------------------------------------
# CLI entry point (impure). `python -m durable.reporting.report --type ...`
#
# Nothing above this line does I/O. Everything below it does: it reads the
# DuckDB PIT store, backtest output JSON on disk, config.yaml, and git, then
# calls the pure functions above with a real `data` dict and writes the
# result to reports/report_<type>_<date>.json.
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# docs/07 section 1 names five report types: Pulse, Quarterly Review, Research
# Bulletin, Event Report, Annual Assessment. The ReportType enum above (already
# implemented, not touched by this ticket) instead has QUARTERLY, ANNUAL, ADHOC,
# ATTRIBUTION, RESEARCH -- ATTRIBUTION where docs/07 has "Pulse" and ADHOC where
# docs/07 has "Event". That naming mismatch predates this CLI. Rather than
# silently picking a resolution, it is spelled out here:
#   "event" -> ADHOC        docs/07: "Event Report (triggered)"; matches
#                            _build_adhoc()'s own docstring, "ad-hoc
#                            event-triggered report".
#   "pulse" -> ATTRIBUTION  the only ReportType left unclaimed. A Brinson
#                            allocation/selection/interaction breakdown is a
#                            defensible "one screen" summary, but this is a
#                            naming patch, not a semantic fit. A true weekly
#                            Pulse report (docs/07: "one screen") may deserve
#                            its own ReportType and builder in a future
#                            ticket -- flagged, not fixed, here.
_CLI_TYPE_TO_REPORT_TYPE: dict[str, ReportType] = {
    "pulse": ReportType.ATTRIBUTION,
    "quarterly": ReportType.QUARTERLY,
    "research": ReportType.RESEARCH,
    "event": ReportType.ADHOC,
    "annual": ReportType.ANNUAL,
}


class DataUnavailableError(RuntimeError):
    """Raised when the CLI cannot honestly assemble a report's `data` dict.

    Caught by main() and printed as a plain message, never a raw traceback --
    "no data/history yet" is the expected, common state this early in the
    project, not a bug. Never caught silently: the message always says
    exactly which field(s) are missing and why, so a missing input is never
    mistaken for a working report with fabricated numbers in it.
    """


def _git_commit_hash() -> str:
    """Best-effort current commit hash; 'unknown' if git is unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _config_hash() -> str:
    """Sha256 of config.yaml's parsed contents; 'no-config' if it doesn't exist yet."""
    from durable.config import ConfigError, load_config

    try:
        config = load_config()
    except ConfigError:
        return "no-config"
    blob = json.dumps(config, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def _resolve_db_path(db_path_arg: str | None) -> Path:
    """--db-path wins outright; otherwise config/config.yaml's data.duckdb_path; otherwise
    the project default. Mirrors durable.data.ingest._resolve_db_path / durable.data.firewall
    for consistency, but tolerates a missing config.yaml (report generation is read-only and
    should not hard-require the safety-relevant config file to exist)."""
    if db_path_arg:
        p = Path(db_path_arg)
        return p if p.is_absolute() else PROJECT_ROOT / p

    from durable.config import ConfigError, load_config

    try:
        config = load_config()
        db_path_cfg = config.get("data", {}).get("duckdb_path", "data/durable.duckdb")
    except ConfigError:
        db_path_cfg = "data/durable.duckdb"
    db_path = Path(db_path_cfg)
    return db_path if db_path.is_absolute() else PROJECT_ROOT / db_path


def _rel(path: Path) -> str:
    """path relative to PROJECT_ROOT for display, or the absolute path if `path` is
    outside the repo (e.g. --out-dir/--db-path pointed somewhere else, as tests do).
    Path.relative_to() raises ValueError in that case; every message in this CLI must
    degrade to an absolute path instead of a raw traceback."""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _quarter_label(d: date) -> str:
    """'2026-Q3' style label for a date. Descriptive metadata only, not a PIT boundary."""
    q = (d.month - 1) // 3 + 1
    return f"{d.year}-Q{q}"


def _find_latest_backtest_json(reports_dir: Path, segment: str | None) -> Path | None:
    """Most recently written reports/backtest_<segment>_*.json (see backtest/engine.py's
    own CLI, which is the only thing in this repo that currently writes one)."""
    pattern = f"backtest_{segment}_*.json" if segment else "backtest_*.json"
    candidates = sorted(reports_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _load_factor_ic_table(conn: Any) -> dict[str, dict[str, float | int]]:
    """Summarize the factor_ic table: mean IC and a simple across-period t-stat per factor.

    Not read via store.as_of(): factor_ic rows (src/durable/data/store.py's schema) have no
    `available_at` column -- they are already-computed research artifacts, not raw PIT data,
    so as_of()'s look-ahead filter does not apply here.
    """
    import numpy as np

    df = conn.execute("SELECT factor, ic FROM factor_ic WHERE ic IS NOT NULL").fetchdf()
    if df.empty:
        return {}
    table: dict[str, dict[str, float | int]] = {}
    for factor, group in df.groupby("factor"):
        ic_values = group["ic"].to_numpy(dtype=float)
        n = len(ic_values)
        mean_ic = float(np.mean(ic_values))
        std_ic = float(np.std(ic_values, ddof=1)) if n > 1 else 0.0
        t_stat = float(mean_ic / (std_ic / np.sqrt(n))) if std_ic > 0 else 0.0
        table[str(factor)] = {"ic": mean_ic, "t_stat": t_stat, "n_periods": n}
    return table


def _assemble_research_data(args: Any, reports_dir: Path, db_path: Path) -> dict[str, Any]:
    """Real research-bulletin data: git commit, config hash, DuckDB snapshot IDs and factor
    IC (if any have been computed), and the trial count from reports/experiment_log.csv.

    pbo and contamination_verdict are honestly left null/"not_yet_assessed" rather than
    fabricated: no `make cpcv` run and no alpha-decay test (TICKET-045) have persisted a
    result anywhere in this repo as of this ticket. See the `disclosure` field for details.
    """
    from durable.reporting.inference import ExperimentLogMissingError, require_experiment_log

    as_of_date = date.fromisoformat(args.as_of) if args.as_of else date.today()

    snapshot_ids: list[str] = []
    factor_ic_table: dict[str, dict[str, float | int]] = {}
    if db_path.exists():
        from durable.data import store

        conn = store.get_conn(db_path)
        try:
            snaps = store.list_snapshots(conn)
            if not snaps.empty:
                snapshot_ids = sorted(snaps["snapshot_id"].unique().tolist())
            factor_ic_table = _load_factor_ic_table(conn)
        finally:
            conn.close()

    experiment_log_path = reports_dir / "experiment_log.csv"
    try:
        trial_count = require_experiment_log(experiment_log_path)
    except ExperimentLogMissingError as exc:
        raise DataUnavailableError(str(exc)) from exc

    notes: list[str] = []
    if not factor_ic_table:
        notes.append(
            "factor_ic_table is empty: no `make ic FACTOR=...` results are in the store yet."
        )
    notes.append(
        "pbo is null: no `make cpcv` run has persisted a PBO result anywhere in this repo yet."
    )
    notes.append(
        "contamination_verdict is 'not_yet_assessed': no alpha-decay test result "
        "(TICKET-045, durable.signals.contamination) has been persisted yet."
    )

    return {
        "period": _quarter_label(as_of_date),
        "methodology_snapshot": {
            "git_commit": _git_commit_hash(),
            "config_hash": _config_hash(),
            "snapshot_ids": snapshot_ids,
            "bootstrap_method": "stationary_block",
        },
        "factor_ic_table": factor_ic_table,
        "pbo": None,
        "contamination_verdict": "not_yet_assessed",
        "trial_count": trial_count,
        "seeds": [42],
        "disclosure": " ".join(notes),
    }


def _assemble_performance_based_data(
    cli_type: str, internal_type: ReportType, args: Any, reports_dir: Path
) -> dict[str, Any]:
    """quarterly / annual / event(adhoc) / pulse(attribution): looks for real backtest
    output and computes real risk metrics from it, then honestly refuses rather than
    fabricating the fields no module in this repo persists yet (benchmark returns aligned
    to rebalance dates, position weights, turnover, or a kill-criteria evaluator).

    Always raises DataUnavailableError today, because that upstream data genuinely does not
    exist anywhere in this codebase yet -- see the final report for what's missing and why.
    Pass --data-json with a pre-assembled dict (shape: tests/test_report.py's fixtures) to
    generate one of these report types before that upstream data exists.
    """
    backtest_path = _find_latest_backtest_json(reports_dir, args.segment)
    if backtest_path is None:
        raise DataUnavailableError(
            f"No backtest output found in {_rel(reports_dir)}/ (looked "
            f"for backtest_{args.segment or '*'}_*.json). Run `make backtest "
            "SEGMENT=design` (or validation/holdout) first, or pass --data-json with a "
            "pre-assembled report data dict."
        )
    payload = json.loads(backtest_path.read_text())
    period_returns = payload.get("period_returns") or []
    if not period_returns:
        raise DataUnavailableError(f"{backtest_path.name} has no period_returns to report on.")

    import numpy as np

    from durable.reporting.performance import compute_risk_metrics

    risk = compute_risk_metrics(np.array(period_returns, dtype=float))

    missing: set[str] = set()
    if internal_type in (ReportType.QUARTERLY, ReportType.ANNUAL, ReportType.ATTRIBUTION):
        missing.update({"benchmark_return", "kill_criteria"})
    if internal_type == ReportType.QUARTERLY:
        missing.update({"holdings_count", "turnover_pct"})
    if internal_type == ReportType.ATTRIBUTION:
        missing.update(
            {
                "allocation_effect",
                "selection_effect",
                "interaction_effect",
                "factor_exposures",
            }
        )
    if internal_type == ReportType.ANNUAL:
        missing.update({"continue_decision", "since_inception_return"})
    if internal_type == ReportType.ADHOC:
        missing.update({"trigger", "timestamp", "summary", "affected_positions"})

    raise DataUnavailableError(
        f"Found real backtest output at {_rel(backtest_path)} "
        f"(cagr={payload.get('cagr', 0.0):+.2%}, {len(period_returns)} periods, "
        f"volatility_ann={risk.volatility_ann:.2%}, max_drawdown={risk.max_drawdown:.2%}), "
        f"but the '{cli_type}' report additionally requires: {', '.join(sorted(missing))}. "
        "None of these are produced by any pipeline in this repo yet: there is no persisted "
        "benchmark return series aligned to rebalance dates, no positions/turnover output, "
        "and no kill-criteria evaluator. Fabricating them would misrepresent the portfolio, "
        "so this CLI refuses. Pass --data-json with a complete data dict instead."
    )


def _assemble_data(
    cli_type: str, internal_type: ReportType, args: Any, reports_dir: Path, db_path: Path
) -> dict[str, Any]:
    if args.data_json:
        data_path = Path(args.data_json)
        if not data_path.is_file():
            raise DataUnavailableError(f"--data-json path not found: {data_path}")
        return json.loads(data_path.read_text())
    if internal_type == ReportType.RESEARCH:
        return _assemble_research_data(args, reports_dir, db_path)
    return _assemble_performance_based_data(cli_type, internal_type, args, reports_dir)


def _log_report_run(cli_type: str, out_path: Path, json_str: str, reports_dir: Path) -> None:
    """Append a row to reports/report_log.csv -- the log `research/preregister.py
    --reproduce` reads.

    Deliberately NOT reports/experiment_log.csv: that file's row count is fed directly to
    the Deflated Sharpe / PBO trial count via
    durable.reporting.inference.require_experiment_log(). Report generation is not a
    research trial; logging it there would silently inflate the trial count every time
    someone runs `make report`, which is exactly the kind of quietly-widened-denominator
    problem this project's own rules (docs/12, research-integrity.md #2) exist to prevent.
    A logging failure here is a warning, not a fatal error: the report itself already
    succeeded and is the primary deliverable.
    """
    try:
        from durable.research import preregister

        preregister.append_report_log_row(
            reports_dir / "report_log.csv",
            {
                "run_id": (
                    f"report_{cli_type}_{hashlib.sha256(out_path.name.encode()).hexdigest()[:8]}"
                ),
                "report_type": cli_type,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "commit_hash": _git_commit_hash(),
                "config_hash": _config_hash(),
                "report_path": _rel(out_path),
                "output_sha256": hashlib.sha256(json_str.encode("utf-8")).hexdigest(),
            },
        )
    except Exception as exc:  # noqa: BLE001 - never let logging failure hide a good report
        print(f"Warning: could not append to report_log.csv: {exc}")


def _write_factor_ic_figure(
    factor_ic_table: dict[str, dict[str, float | int]], out_path: Path
) -> None:
    """A real 300dpi PNG (docs/07 section 3: figures/*.png). A placeholder panel, honestly
    labeled, when there is no factor_ic data yet -- never an empty or fabricated chart."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from durable.reporting.research_export import FIGURE_DPI

    fig, ax = plt.subplots(figsize=(6, 4))
    if factor_ic_table:
        factors = sorted(factor_ic_table)
        ic_values = [factor_ic_table[f].get("ic", 0.0) for f in factors]
        ax.bar(factors, ic_values)
        ax.axhline(0.0, color="black", linewidth=0.8)
        ax.set_ylabel("Mean rank IC")
        ax.set_title("Factor IC")
        fig.autofmt_xdate(rotation=30)
    else:
        ax.text(0.5, 0.5, "No factor_ic data recorded yet", ha="center", va="center")
        ax.set_axis_off()
    fig.tight_layout()
    fig.savefig(out_path, dpi=FIGURE_DPI)
    plt.close(fig)


def _run_research_export(report: dict[str, Any], as_of_date: date) -> Path:
    """`--export`: the JSON/CSV/LaTeX/300dpi-figure bundle described in docs/07 section 3,
    built from durable.reporting.research_export's already-tested Artifact machinery.

    Only the artifacts this repo can honestly populate today are written; everything else
    (returns.csv, attribution.csv, positions.csv) is explicitly listed as omitted, with why,
    in appendix.md -- never silently absent.
    """
    from durable.reporting import research_export as rx

    export_dir = PROJECT_ROOT / "research" / f"export_{as_of_date.isoformat()}"
    (export_dir / "tables").mkdir(parents=True, exist_ok=True)
    (export_dir / "figures").mkdir(parents=True, exist_ok=True)

    methodology_snapshot = report.get("methodology_snapshot") or {}
    factor_ic_table: dict[str, dict[str, float | int]] = report.get("factor_ic_table") or {}
    snapshot_ids = methodology_snapshot.get("snapshot_ids") or []

    metadata = rx.ArtifactMetadata(
        git_commit=str(methodology_snapshot.get("git_commit", "unknown")),
        config_hash=str(methodology_snapshot.get("config_hash", "no-config")),
        seed=42,
        snapshot_id=",".join(snapshot_ids) if snapshot_ids else "none",
    )
    n_periods = max((v.get("n_periods", 0) for v in factor_ic_table.values()), default=0)
    pbo = report.get("pbo")
    disclosure = rx.DisclosureBlock(
        source="durable-alpha internal report/research pipeline",
        date=as_of_date.isoformat(),
        sample_period_start=as_of_date.isoformat(),
        sample_period_end=as_of_date.isoformat(),
        n_periods=int(n_periods),
        status="paper",
        costs_modeled="not modeled in this export (no backtest cost output persisted yet)",
        trials_logged=int(report.get("trial_count") or 0),
        pbo=float(pbo) if pbo is not None else 1.0,
        contamination_verdict=str(report.get("contamination_verdict", "not_yet_assessed")),
        limitations=(
            (report.get("disclosure") or "")
            + " Single realized path; small live sample; export generated with no ingested "
            "market data as of this run."
        ).strip(),
    )

    artifacts = []

    stats_content = json.dumps(report, sort_keys=True, indent=2)
    (export_dir / "metrics.json").write_text(stats_content)
    artifacts.append(
        rx.generate_artifact(rx.ArtifactType.STATISTICS, stats_content, metadata, disclosure)
    )

    csv_lines = ["factor,ic,t_stat,n_periods"]
    for factor, stats in sorted(factor_ic_table.items()):
        csv_lines.append(
            f"{factor},{stats.get('ic', float('nan')):.6f},"
            f"{stats.get('t_stat', float('nan')):.4f},{stats.get('n_periods', 0)}"
        )
    csv_content = "\n".join(csv_lines) + "\n"
    (export_dir / "factor_ic.csv").write_text(csv_content)
    artifacts.append(
        rx.generate_artifact(rx.ArtifactType.TABLES, csv_content, metadata, disclosure)
    )

    tex_lines = [
        "\\begin{tabular}{lrrr}",
        "\\toprule",
        "Factor & IC & t-stat & N periods \\\\",
        "\\midrule",
    ]
    for factor, stats in sorted(factor_ic_table.items()):
        tex_lines.append(
            f"{factor} & {stats.get('ic', 0.0):.4f} & {stats.get('t_stat', 0.0):.2f} & "
            f"{stats.get('n_periods', 0)} \\\\"
        )
    tex_lines += ["\\bottomrule", "\\end{tabular}"]
    (export_dir / "tables" / "factor_ic.tex").write_text("\n".join(tex_lines) + "\n")

    fig_path = export_dir / "figures" / "factor_ic.png"
    _write_factor_ic_figure(factor_ic_table, fig_path)
    fig_note = (
        "figure written to figures/factor_ic.png"
        if factor_ic_table
        else "placeholder: no factor_ic data yet"
    )
    artifacts.append(rx.generate_artifact(rx.ArtifactType.FIGURES, fig_note, metadata, disclosure))

    dd_content = (
        "factor: factor name (str)\n"
        "ic: mean rank information coefficient across scored periods (float)\n"
        "t_stat: IC t-statistic across periods, mean / (sample stdev / sqrt(n)) (float; "
        "0.0 if n_periods < 2)\n"
        "n_periods: number of as_of dates with a recorded IC for this factor (int)\n"
    )
    (export_dir / "data_dictionary.txt").write_text(dd_content)
    artifacts.append(
        rx.generate_artifact(rx.ArtifactType.DATA_DICTIONARY, dd_content, metadata, disclosure)
    )

    changelog_content = (
        f"{as_of_date.isoformat()}: research export generated at commit {metadata.git_commit}.\n"
    )
    (export_dir / "changelog.md").write_text(changelog_content)
    artifacts.append(
        rx.generate_artifact(rx.ArtifactType.CHANGELOG, changelog_content, metadata, disclosure)
    )

    appendix_content = (
        "# Appendix\n\nFull research report JSON is in metrics.json.\n\n"
        "## Artifacts intentionally NOT produced in this bundle\n"
        "- returns.csv, attribution.csv, positions.csv: no module in this repo persists a "
        "portfolio return series, Brinson attribution, or position weights yet. Fabricating "
        "them here would be worse than omitting them.\n"
    )
    (export_dir / "appendix.md").write_text(appendix_content)
    artifacts.append(
        rx.generate_artifact(rx.ArtifactType.APPENDIX, appendix_content, metadata, disclosure)
    )

    for artifact in artifacts:
        rx.validate_artifact(artifact)

    (export_dir / "methodology.md").write_text(rx.methodology_pins(artifacts))

    return export_dir


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate a performance/research report (docs/07). Reads real data "
        "where it exists and refuses, with a clear message, to fabricate the rest."
    )
    parser.add_argument(
        "--type",
        required=True,
        choices=sorted(_CLI_TYPE_TO_REPORT_TYPE),
        help="Report type",
    )
    parser.add_argument(
        "--data-json",
        default=None,
        help="Pre-assembled `data` dict as JSON, bypassing auto-assembly entirely",
    )
    parser.add_argument(
        "--segment",
        default=None,
        help="Which reports/backtest_<segment>_*.json to read (default: most recent of any)",
    )
    parser.add_argument(
        "--as-of",
        default=None,
        help="ISO date for the report period label (default: today)",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Override the DuckDB path (default: config/config.yaml data.duckdb_path)",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Override the report output directory (default: reports/)",
    )
    parser.add_argument(
        "--export",
        action="store_true",
        help="Also write the research export bundle to research/export_<date>/ "
        "(only valid with --type research)",
    )
    args = parser.parse_args(argv)

    internal_type = _CLI_TYPE_TO_REPORT_TYPE[args.type]

    if args.export and internal_type != ReportType.RESEARCH:
        parser.error("--export is only valid with --type research")

    reports_dir = Path(args.out_dir) if args.out_dir else PROJECT_ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    db_path = _resolve_db_path(args.db_path)

    try:
        data = _assemble_data(args.type, internal_type, args, reports_dir, db_path)
        report = generate_report(internal_type, data)
    except (DataUnavailableError, ReportValidationError) as exc:
        print(str(exc))
        return 1

    as_of_date = date.fromisoformat(args.as_of) if args.as_of else date.today()
    json_str = report_to_json(report)
    out_path = reports_dir / f"report_{args.type}_{as_of_date.isoformat()}.json"
    out_path.write_text(json_str)
    print(f"Wrote {_rel(out_path)}")

    _log_report_run(args.type, out_path, json_str, reports_dir)

    if args.export:
        try:
            export_dir = _run_research_export(report, as_of_date)
        except Exception as exc:  # noqa: BLE001 - a failed bundle must not hide a good report
            print(f"Report written, but the research export bundle failed: {exc}")
            return 1
        print(f"Research export bundle written to {_rel(export_dir)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
