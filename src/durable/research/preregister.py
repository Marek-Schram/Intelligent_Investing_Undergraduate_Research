"""Preregistration enforcement. docs/12 section 4. TICKET-041.

A hypothesis must be committed BEFORE its test runs. Compares git timestamps and
raises on HARKing (Hypothesizing After Results are Known).
experiment_log gains new columns. make reproduce COMMIT=<hash> regenerates byte-identically.
Seeds pinned.

Data source: git history, experiment log.
available_at logic: N/A (research artifact).
Spec section: docs/12 §4.

PURE FUNCTIONS ONLY (up to the CLI section at the bottom): no I/O, network, wall-clock, or
config lookups. Timestamp comparison functions are pure — they take timestamps as inputs.
The CLI section does real file I/O and shells out to git; see its module comment for the
`--reproduce` design decision (rigorous git-worktree rebuild vs. lightweight same-checkout
hash verification) and why the lightweight design was chosen.
"""

from __future__ import annotations

import csv
import hashlib
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


class HARKingError(ValueError):
    """Raised when a hypothesis was registered AFTER its test ran."""

    pass


class ReproducibilityError(ValueError):
    """Raised when reproduction fails."""

    pass


@dataclass(frozen=True)
class Hypothesis:
    """A preregistered hypothesis."""

    hypothesis_id: str
    description: str
    registered_at: datetime
    commit_hash: str
    factor: str
    expected_direction: str  # "positive", "negative", "none"
    seed: int


@dataclass(frozen=True)
class ExperimentRun:
    """One experiment run in the log."""

    run_id: str
    hypothesis_id: str
    run_at: datetime
    commit_hash: str
    config_hash: str
    seed: int
    result_sharpe: float | None = None
    result_ic: float | None = None
    model_version: str = ""
    prompt_version: str = ""


@dataclass(frozen=True)
class ReproductionSpec:
    """Everything needed to reproduce a run byte-identically."""

    commit_hash: str
    config_hash: str
    seed: int
    model_version: str
    prompt_version: str
    snapshot_id: str = ""


def check_harking(
    hypothesis_registered_at: datetime,
    test_run_at: datetime,
) -> None:
    """Raise HARKingError if hypothesis was registered after the test ran.

    Compares git timestamps: registration must precede the run.
    """
    if hypothesis_registered_at > test_run_at:
        raise HARKingError(
            f"Hypothesis registered at {hypothesis_registered_at} but test ran at "
            f"{test_run_at}. This is HARKing — hypothesizing after results are known."
        )


def validate_preregistration(
    hypothesis: Hypothesis,
    run: ExperimentRun,
) -> None:
    """Validate that a hypothesis was preregistered before the run."""
    if hypothesis.hypothesis_id != run.hypothesis_id:
        raise ValueError("hypothesis_id mismatch")
    check_harking(hypothesis.registered_at, run.run_at)


def build_reproduction_spec(run: ExperimentRun) -> ReproductionSpec:
    """Build a reproduction spec from an experiment run. Seeds pinned."""
    return ReproductionSpec(
        commit_hash=run.commit_hash,
        config_hash=run.config_hash,
        seed=run.seed,
        model_version=run.model_version,
        prompt_version=run.prompt_version,
    )


def verify_reproduction(
    original: ReproductionSpec,
    reproduced: ReproductionSpec,
) -> None:
    """Verify byte-identical reproduction.

    Raises ReproducibilityError if specs don't match.
    """
    if original.commit_hash != reproduced.commit_hash:
        raise ReproducibilityError(
            f"Commit mismatch: {original.commit_hash} vs {reproduced.commit_hash}"
        )
    if original.config_hash != reproduced.config_hash:
        raise ReproducibilityError(
            f"Config hash mismatch: {original.config_hash} vs {reproduced.config_hash}"
        )
    if original.seed != reproduced.seed:
        raise ReproducibilityError(f"Seed mismatch: {original.seed} vs {reproduced.seed}")


EXPERIMENT_LOG_COLUMNS = [
    "run_id",
    "hypothesis_id",
    "run_at",
    "commit_hash",
    "config_hash",
    "seed",
    "result_sharpe",
    "result_ic",
    "model_version",
    "prompt_version",
]


# ---------------------------------------------------------------------------
# CLI entry point (impure). `python -m durable.research.preregister --reproduce COMMIT`
#
# DESIGN DECISION — read this before changing --reproduce.
#
# docs/12 §3 says "make reproduce COMMIT=<hash> must regenerate a prior report
# byte-identically." Two designs were possible:
#   (a) RIGOROUS: `git worktree add` a fresh checkout of COMMIT, re-run the report/backtest
#       command that produced the original artifact in that isolated worktree, and byte-diff
#       the result against what's on record. This is the only design that actually proves
#       "this commit reproduces this output," because it isolates uncommitted local changes
#       and any drift since COMMIT.
#   (b) LIGHTWEIGHT: read reports/report_log.csv for the run recorded at COMMIT, and check
#       whether the artifact currently on disk still hashes to what was recorded — in the
#       CURRENT checkout, without isolating it from local changes.
#
# This module implements (b). Reasons, in order of weight:
#   1. There is no recorded "command" for a logged run (report_log.csv, like
#      experiment_log.csv's documented schema in docs/12, stores parameters and results, not
#      an executable command line) and no ticket has defined one. Guessing which command to
#      re-run in a worktree risks silently running the wrong pipeline and returning a false
#      PASS or FAIL — worse than not automating this at all.
#   2. Four other agents are concurrently committing to this same repository while this
#      ticket is being implemented. `git worktree add <path> <commit>` while sibling agents
#      may be mid-commit is a correctness and safety risk (worktree/lock contention) that is
#      disproportionate to what a single reporting CLI needs to resolve today.
#   3. As of this ticket there is no DuckDB file and no ingested data in this environment —
#      a full worktree rebuild of the backtest has nothing to reproduce against yet. Building
#      elaborate git-worktree orchestration now, untested against real data, is more likely
#      to be silently wrong than a correctly-scoped simpler tool.
#   4. (b) is fully and correctly implementable today, testable with hand-built fixtures, and
#      gives an honest, well-defined guarantee.
#
# The guarantee (b) gives is real but WEAKER than (a), and the CLI says so on every run: it
# answers "has the recorded artifact drifted since it was logged?" (catches silent
# non-determinism and accidental edits), NOT "does a clean checkout of COMMIT reproduce this
# output?" (which would also catch uncommitted changes and code drift since COMMIT). When the
# current git HEAD does not match the requested COMMIT, this CLI refuses to report PASS,
# because under those conditions it cannot back up even the weaker guarantee.
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Columns for reports/report_log.csv, the reproducibility log written by
# durable.reporting.report's CLI on every successful report generation. Deliberately a
# SEPARATE file from reports/experiment_log.csv (whose schema is documented in docs/12 §3 and
# whose row count feeds Deflated Sharpe / PBO's trial count via
# durable.reporting.inference.require_experiment_log) — logging report-generation events
# there would silently inflate the trial count. See report.py's `_log_report_run` docstring.
REPORT_LOG_COLUMNS = [
    "run_id",
    "report_type",
    "generated_at",
    "commit_hash",
    "config_hash",
    "report_path",
    "output_sha256",
]


class ReproduceCLIError(RuntimeError):
    """Raised for CLI-level failures (missing log, bad commit, I/O errors).

    Caught by main() and printed as a plain message, never a raw traceback.
    """


def append_report_log_row(log_path: str | Path, row: dict[str, str]) -> None:
    """Append one row to reports/report_log.csv, creating it with REPORT_LOG_COLUMNS as the
    header if it doesn't exist yet. `row` must be a subset of REPORT_LOG_COLUMNS; missing
    keys are written as empty strings so the file stays a valid fixed-width CSV."""
    log_path = Path(log_path)
    unknown = set(row) - set(REPORT_LOG_COLUMNS)
    if unknown:
        raise ValueError(f"Unknown report_log.csv column(s): {sorted(unknown)}")

    log_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not log_path.exists() or log_path.stat().st_size == 0
    with log_path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REPORT_LOG_COLUMNS)
        if is_new:
            writer.writeheader()
        writer.writerow({col: row.get(col, "") for col in REPORT_LOG_COLUMNS})


def read_report_log(log_path: str | Path) -> list[dict[str, str]]:
    """Read reports/report_log.csv. Raises ReproduceCLIError if it doesn't exist —
    'no runs logged yet' must be a clear message, not a silent empty list that makes
    `--reproduce` claim there's nothing to check when really nobody ran `make report` yet."""
    log_path = Path(log_path)
    if not log_path.is_file():
        raise ReproduceCLIError(
            f"{log_path} does not exist. No report has been logged yet — run `make report "
            "TYPE=<type>` first, then `make reproduce COMMIT=<hash>` against its commit."
        )
    with log_path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    return rows


def _current_git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _rel(path: Path) -> str:
    """path relative to PROJECT_ROOT for display, or the absolute path if `path` is
    outside the repo (e.g. --report-log pointed somewhere else, as tests do).
    Path.relative_to() raises ValueError in that case; every message in this CLI must
    degrade to an absolute path instead of a raw traceback."""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _matches_commit(row_commit: str, requested: str) -> bool:
    """Tolerate abbreviated hashes in either direction, like git itself does."""
    if not row_commit or not requested:
        return False
    return row_commit.startswith(requested) or requested.startswith(row_commit)


def reproduce(commit: str, report_log_path: Path | None = None) -> int:
    """`make reproduce COMMIT=<hash>`. See the module comment above for the design decision.

    Returns a process exit code (0 = every matched run verified AND the current checkout is
    at `commit`; 1 = no matching run, a hash mismatch, or a checkout mismatch).
    """
    report_log_path = report_log_path or (PROJECT_ROOT / "reports" / "report_log.csv")

    try:
        rows = read_report_log(report_log_path)
    except ReproduceCLIError as exc:
        print(str(exc))
        return 1

    matches = [r for r in rows if _matches_commit(r.get("commit_hash", ""), commit)]
    if not matches:
        logged_commits = sorted({r.get("commit_hash", "") for r in rows if r.get("commit_hash")})
        print(
            f"No run recorded at commit {commit!r} in {_rel(report_log_path)} "
            f"({len(rows)} run(s) logged, at commit(s): {logged_commits})."
        )
        return 1

    current_head = _current_git_commit()
    head_matches = current_head is not None and _matches_commit(current_head, commit)
    if not head_matches:
        print(
            "WARNING: current git HEAD "
            f"({current_head or 'unknown'}) does not match the requested commit "
            f"({commit}). This CLI verifies the lightweight guarantee only (see the design "
            "comment in this module) — it cannot certify reproduction from a different "
            "checkout, so this run will be reported as UNVERIFIED rather than PASS even if "
            "file hashes happen to match."
        )

    all_ok = True
    for row in matches:
        report_path = PROJECT_ROOT / row.get("report_path", "")
        run_id = row.get("run_id", "?")
        recorded_hash = row.get("output_sha256", "")
        if not report_path.is_file():
            print(f"FAIL {run_id}: recorded output file missing: {report_path}")
            all_ok = False
            continue
        current_hash = _sha256_file(report_path)
        if current_hash != recorded_hash:
            print(
                f"FAIL {run_id}: {_rel(report_path)} hash mismatch "
                f"(recorded {recorded_hash[:12]}..., now {current_hash[:12]}...)"
            )
            all_ok = False
        elif not head_matches:
            print(
                f"UNVERIFIED {run_id}: {_rel(report_path)} hash matches "
                "the record, but current HEAD != requested commit — see warning above."
            )
            all_ok = False
        else:
            print(f"PASS {run_id}: {_rel(report_path)} matches the record.")

    return 0 if all_ok else 1


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Verify that a logged report's output still matches what was recorded "
        "at a given commit (lightweight reproduction check — see the design comment in "
        "this module for what this does and does not prove)."
    )
    parser.add_argument(
        "--reproduce", metavar="COMMIT", required=True, help="Commit hash to check"
    )
    parser.add_argument(
        "--report-log",
        default=None,
        help="Override reports/report_log.csv path (mainly for tests)",
    )
    args = parser.parse_args(argv)

    report_log_path = Path(args.report_log) if args.report_log else None
    return reproduce(args.reproduce, report_log_path)


if __name__ == "__main__":
    raise SystemExit(main())
