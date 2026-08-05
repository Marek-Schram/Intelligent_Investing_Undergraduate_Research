"""Tests for preregistration. TICKET-041."""

from __future__ import annotations

from datetime import datetime

import pytest

from durable.research.preregister import (
    EXPERIMENT_LOG_COLUMNS,
    ExperimentRun,
    HARKingError,
    Hypothesis,
    ReproducibilityError,
    ReproductionSpec,
    build_reproduction_spec,
    check_harking,
    validate_preregistration,
    verify_reproduction,
)


class TestHARKingDetection:
    """Raises on HARKing — acceptance criterion."""

    def test_hypothesis_after_run_raises(self):
        """Hypothesis registered AFTER test ran = HARKing."""
        with pytest.raises(HARKingError, match="HARKing"):
            check_harking(
                hypothesis_registered_at=datetime(2025, 6, 15, 10, 0),
                test_run_at=datetime(2025, 6, 14, 10, 0),
            )

    def test_hypothesis_before_run_ok(self):
        """Hypothesis registered BEFORE test ran = legitimate."""
        check_harking(
            hypothesis_registered_at=datetime(2025, 6, 10, 10, 0),
            test_run_at=datetime(2025, 6, 15, 10, 0),
        )  # No raise

    def test_same_time_ok(self):
        """Registered at same instant as run is borderline acceptable."""
        ts = datetime(2025, 6, 15, 10, 0)
        check_harking(hypothesis_registered_at=ts, test_run_at=ts)  # No raise


class TestValidatePreregistration:
    def test_valid_preregistration(self):
        hyp = Hypothesis(
            hypothesis_id="H1",
            description="Durability predicts returns",
            registered_at=datetime(2025, 6, 1),
            commit_hash="abc123",
            factor="durability",
            expected_direction="positive",
            seed=42,
        )
        run = ExperimentRun(
            run_id="R1",
            hypothesis_id="H1",
            run_at=datetime(2025, 6, 10),
            commit_hash="def456",
            config_hash="cfg789",
            seed=42,
        )
        validate_preregistration(hyp, run)  # No raise

    def test_mismatched_hypothesis_id(self):
        hyp = Hypothesis("H1", "desc", datetime(2025, 6, 1), "abc", "f", "positive", 42)
        run = ExperimentRun("R1", "H2", datetime(2025, 6, 10), "def", "cfg", 42)
        with pytest.raises(ValueError, match="mismatch"):
            validate_preregistration(hyp, run)


class TestReproduction:
    """make reproduce COMMIT=<hash> regenerates byte-identically — acceptance criterion."""

    def test_build_reproduction_spec(self):
        run = ExperimentRun(
            run_id="R1",
            hypothesis_id="H1",
            run_at=datetime(2025, 6, 10),
            commit_hash="abc123",
            config_hash="cfg789",
            seed=42,
            model_version="claude-3.5",
            prompt_version="v1.0",
        )
        spec = build_reproduction_spec(run)
        assert spec.commit_hash == "abc123"
        assert spec.config_hash == "cfg789"
        assert spec.seed == 42

    def test_identical_specs_pass(self):
        spec = ReproductionSpec("abc", "cfg", 42, "v1", "p1")
        verify_reproduction(spec, spec)  # No raise

    def test_different_commit_fails(self):
        orig = ReproductionSpec("abc", "cfg", 42, "v1", "p1")
        repro = ReproductionSpec("xyz", "cfg", 42, "v1", "p1")
        with pytest.raises(ReproducibilityError, match="Commit"):
            verify_reproduction(orig, repro)

    def test_different_seed_fails(self):
        orig = ReproductionSpec("abc", "cfg", 42, "v1", "p1")
        repro = ReproductionSpec("abc", "cfg", 99, "v1", "p1")
        with pytest.raises(ReproducibilityError, match="Seed"):
            verify_reproduction(orig, repro)


class TestSeedsPinned:
    """Seeds pinned — acceptance criterion."""

    def test_hypothesis_has_seed(self):
        hyp = Hypothesis("H1", "desc", datetime(2025, 1, 1), "abc", "f", "positive", 42)
        assert hyp.seed == 42

    def test_run_has_seed(self):
        run = ExperimentRun("R1", "H1", datetime(2025, 1, 1), "abc", "cfg", 99)
        assert run.seed == 99


class TestExperimentLogColumns:
    """experiment_log gains new columns — acceptance criterion."""

    def test_has_model_version(self):
        assert "model_version" in EXPERIMENT_LOG_COLUMNS

    def test_has_prompt_version(self):
        assert "prompt_version" in EXPERIMENT_LOG_COLUMNS

    def test_has_seed(self):
        assert "seed" in EXPERIMENT_LOG_COLUMNS

    def test_has_config_hash(self):
        assert "config_hash" in EXPERIMENT_LOG_COLUMNS
