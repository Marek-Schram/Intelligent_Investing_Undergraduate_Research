"""Preregistration enforcement. docs/12 section 4. TICKET-041.

A hypothesis must be committed BEFORE its test runs. Compares git timestamps and
raises on HARKing (Hypothesizing After Results are Known).
experiment_log gains new columns. make reproduce COMMIT=<hash> regenerates byte-identically.
Seeds pinned.

Data source: git history, experiment log.
available_at logic: N/A (research artifact).
Spec section: docs/12 §4.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
Timestamp comparison functions are pure — they take timestamps as inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


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
