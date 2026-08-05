"""Tests for research export module. TICKET-022."""

from __future__ import annotations

import pytest

from durable.reporting.research_export import (
    FIGURE_DPI,
    Artifact,
    ArtifactMetadata,
    ArtifactType,
    DisclosureBlock,
    generate_artifact,
    methodology_pins,
    regenerate_bytes,
    validate_artifact,
)


@pytest.fixture()
def sample_disclosure() -> DisclosureBlock:
    """A valid disclosure block for testing."""
    return DisclosureBlock(
        source="SEC EDGAR 10-K filings",
        date="2025-06-30",
        sample_period_start="2015-01-01",
        sample_period_end="2025-06-30",
        n_periods=42,
        status="paper",
        costs_modeled="spread, slippage, Almgren-Chriss impact, tax",
        trials_logged=7,
        pbo=0.38,
        contamination_verdict="PASS",
        limitations="Single universe, no international, survivorship mitigated but not eliminated.",
    )


@pytest.fixture()
def sample_metadata() -> ArtifactMetadata:
    """A valid metadata block for testing."""
    return ArtifactMetadata(
        git_commit="abc123def456",
        config_hash="cfg_hash_789",
        seed=42,
        snapshot_id="snap_2025Q2",
        uv_lock_hash="uvlock_aaa",
        llm_model_version="claude-sonnet-4-20250514",
        prompt_version_hash="prompt_bbb",
    )


class TestArtifactTypes:
    """All 7 artifact types are recognized."""

    def test_seven_artifact_types_exist(self):
        """Enum defines exactly 7 artifact types."""
        assert len(ArtifactType) == 7

    def test_all_expected_types_present(self):
        """All named types from the ticket are present."""
        expected = {
            "tables",
            "figures",
            "methodology",
            "statistics",
            "appendix",
            "data_dictionary",
            "changelog",
        }
        actual = {t.value for t in ArtifactType}
        assert actual == expected

    def test_generate_each_type(
        self, sample_disclosure: DisclosureBlock, sample_metadata: ArtifactMetadata
    ):
        """Every artifact type can be generated without error."""
        for art_type in ArtifactType:
            artifact = generate_artifact(
                artifact_type=art_type,
                content=f"content for {art_type.value}",
                metadata=sample_metadata,
                disclosure=sample_disclosure,
            )
            assert artifact.artifact_type == art_type


class TestDisclosureBlock:
    """Disclosure block is required and validated."""

    def test_disclosure_renders_all_fields(self, sample_disclosure: DisclosureBlock):
        """Rendered disclosure contains all required information."""
        rendered = sample_disclosure.render()
        assert "SEC EDGAR 10-K filings" in rendered
        assert "2025-06-30" in rendered
        assert "2015-01-01" in rendered
        assert "42 periods" in rendered
        assert "paper" in rendered
        assert "spread, slippage" in rendered
        assert "7" in rendered
        assert "0.38" in rendered
        assert "PASS" in rendered
        assert "Single universe" in rendered
        assert "single realized path" in rendered

    def test_validate_raises_on_empty_source(
        self, sample_metadata: ArtifactMetadata
    ):
        """Validation raises when disclosure source is empty."""
        bad_disclosure = DisclosureBlock(
            source="",
            date="2025-06-30",
            sample_period_start="2015-01-01",
            sample_period_end="2025-06-30",
            n_periods=42,
            status="paper",
            costs_modeled="spread",
            trials_logged=5,
            pbo=0.40,
            contamination_verdict="PASS",
            limitations="None identified.",
        )
        artifact = Artifact(
            artifact_type=ArtifactType.TABLES,
            content="some table",
            metadata=sample_metadata,
            disclosure=bad_disclosure,
            dpi=72,
        )
        with pytest.raises(ValueError, match="source"):
            validate_artifact(artifact)

    def test_validate_raises_on_empty_limitations(
        self, sample_metadata: ArtifactMetadata
    ):
        """Validation raises when disclosure limitations is empty."""
        bad_disclosure = DisclosureBlock(
            source="valid source",
            date="2025-06-30",
            sample_period_start="2015-01-01",
            sample_period_end="2025-06-30",
            n_periods=42,
            status="paper",
            costs_modeled="spread",
            trials_logged=5,
            pbo=0.40,
            contamination_verdict="PASS",
            limitations="   ",
        )
        artifact = Artifact(
            artifact_type=ArtifactType.STATISTICS,
            content="some stats",
            metadata=sample_metadata,
            disclosure=bad_disclosure,
            dpi=72,
        )
        with pytest.raises(ValueError, match="limitations"):
            validate_artifact(artifact)

    def test_validate_passes_on_valid_artifact(
        self, sample_disclosure: DisclosureBlock, sample_metadata: ArtifactMetadata
    ):
        """Validation passes for a properly formed artifact."""
        artifact = generate_artifact(
            artifact_type=ArtifactType.TABLES,
            content="valid table content",
            metadata=sample_metadata,
            disclosure=sample_disclosure,
        )
        # Should not raise.
        validate_artifact(artifact)


class TestMethodologyPins:
    """methodology.md lists all artifacts."""

    def test_methodology_lists_all_artifacts(
        self, sample_disclosure: DisclosureBlock, sample_metadata: ArtifactMetadata
    ):
        """Generated methodology.md mentions every artifact type present."""
        artifacts = [
            generate_artifact(
                artifact_type=art_type,
                content=f"content for {art_type.value}",
                metadata=sample_metadata,
                disclosure=sample_disclosure,
            )
            for art_type in ArtifactType
        ]
        result = methodology_pins(artifacts)
        assert "# Methodology" in result
        assert "Total artifacts: 7" in result
        for art_type in ArtifactType:
            assert art_type.value in result

    def test_methodology_pins_metadata(
        self, sample_disclosure: DisclosureBlock, sample_metadata: ArtifactMetadata
    ):
        """Methodology output includes git commit, config hash, seeds, snapshot IDs."""
        artifacts = [
            generate_artifact(
                artifact_type=ArtifactType.TABLES,
                content="table data",
                metadata=sample_metadata,
                disclosure=sample_disclosure,
            )
        ]
        result = methodology_pins(artifacts)
        assert "abc123def456" in result
        assert "cfg_hash_789" in result
        assert "42" in result
        assert "snap_2025Q2" in result

    def test_methodology_empty_list(self):
        """Empty artifact list produces a minimal methodology doc."""
        result = methodology_pins([])
        assert "# Methodology" in result
        assert "No artifacts generated" in result


class TestFigureDPI:
    """300dpi setting for figures."""

    def test_figure_dpi_constant(self):
        """FIGURE_DPI is 300."""
        assert FIGURE_DPI == 300

    def test_figure_artifact_gets_300dpi(
        self, sample_disclosure: DisclosureBlock, sample_metadata: ArtifactMetadata
    ):
        """Figure artifacts are generated with 300 DPI."""
        artifact = generate_artifact(
            artifact_type=ArtifactType.FIGURES,
            content="figure spec data",
            metadata=sample_metadata,
            disclosure=sample_disclosure,
        )
        assert artifact.dpi == 300

    def test_non_figure_artifact_gets_default_dpi(
        self, sample_disclosure: DisclosureBlock, sample_metadata: ArtifactMetadata
    ):
        """Non-figure artifacts get the default 72 DPI."""
        for art_type in ArtifactType:
            if art_type == ArtifactType.FIGURES:
                continue
            artifact = generate_artifact(
                artifact_type=art_type,
                content="non-figure content",
                metadata=sample_metadata,
                disclosure=sample_disclosure,
            )
            assert artifact.dpi == 72, f"{art_type.value} should have 72 DPI"


class TestDeterministicRegeneration:
    """Same input produces byte-identical output."""

    def test_same_input_same_bytes(
        self, sample_disclosure: DisclosureBlock, sample_metadata: ArtifactMetadata
    ):
        """Regenerating the same artifact twice yields identical bytes."""
        artifact = generate_artifact(
            artifact_type=ArtifactType.STATISTICS,
            content="IC mean: 0.031, t-stat: 2.1",
            metadata=sample_metadata,
            disclosure=sample_disclosure,
        )
        bytes_1 = regenerate_bytes(artifact)
        bytes_2 = regenerate_bytes(artifact)
        assert bytes_1 == bytes_2

    def test_different_content_different_bytes(
        self, sample_disclosure: DisclosureBlock, sample_metadata: ArtifactMetadata
    ):
        """Different content produces different output bytes."""
        art1 = generate_artifact(
            artifact_type=ArtifactType.STATISTICS,
            content="IC mean: 0.031",
            metadata=sample_metadata,
            disclosure=sample_disclosure,
        )
        art2 = generate_artifact(
            artifact_type=ArtifactType.STATISTICS,
            content="IC mean: 0.045",
            metadata=sample_metadata,
            disclosure=sample_disclosure,
        )
        assert regenerate_bytes(art1) != regenerate_bytes(art2)

    def test_methodology_deterministic(
        self, sample_disclosure: DisclosureBlock, sample_metadata: ArtifactMetadata
    ):
        """methodology_pins produces identical output across calls."""
        artifacts = [
            generate_artifact(
                artifact_type=art_type,
                content=f"stable content for {art_type.value}",
                metadata=sample_metadata,
                disclosure=sample_disclosure,
            )
            for art_type in ArtifactType
        ]
        result_1 = methodology_pins(artifacts)
        result_2 = methodology_pins(artifacts)
        assert result_1 == result_2

    def test_content_hash_deterministic(
        self, sample_disclosure: DisclosureBlock, sample_metadata: ArtifactMetadata
    ):
        """Content hash is stable across regeneration."""
        artifact = generate_artifact(
            artifact_type=ArtifactType.CHANGELOG,
            content="v1.0.0: initial release",
            metadata=sample_metadata,
            disclosure=sample_disclosure,
        )
        hash_1 = artifact.content_hash
        # Create an identical artifact.
        artifact_2 = generate_artifact(
            artifact_type=ArtifactType.CHANGELOG,
            content="v1.0.0: initial release",
            metadata=sample_metadata,
            disclosure=sample_disclosure,
        )
        hash_2 = artifact_2.content_hash
        assert hash_1 == hash_2
