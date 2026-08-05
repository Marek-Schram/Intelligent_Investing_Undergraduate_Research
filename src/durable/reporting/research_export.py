"""Research export module. TICKET-022.

Seven artifact types for research outputs; methodology.md pins everything;
disclosure block on every artifact; 300dpi for figures; deterministic regeneration.

Data source: reporting artifacts (tables, figures, statistics, etc.).
available_at logic: N/A (reporting artifact).
Spec section: docs/07 section 3, docs/12 section 3.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ArtifactType(Enum):
    """Seven artifact types for research export."""

    TABLES = "tables"
    FIGURES = "figures"
    METHODOLOGY = "methodology"
    STATISTICS = "statistics"
    APPENDIX = "appendix"
    DATA_DICTIONARY = "data_dictionary"
    CHANGELOG = "changelog"


# Resolution for figure artifacts (dots per inch).
FIGURE_DPI: int = 300


@dataclass(frozen=True)
class DisclosureBlock:
    """Non-removable disclosure appended to every research artifact.

    Per docs/07 section 3: source, date, limitations are mandatory.
    """

    source: str
    date: str
    sample_period_start: str
    sample_period_end: str
    n_periods: int
    status: str  # "paper" or "live"
    costs_modeled: str
    trials_logged: int
    pbo: float
    contamination_verdict: str
    limitations: str

    def render(self) -> str:
        """Render the disclosure block as a deterministic text string."""
        return (
            f"Source: {self.source}\n"
            f"Date: {self.date}\n"
            f"Sample period: {self.sample_period_start} to {self.sample_period_end}"
            f" ({self.n_periods} periods).\n"
            f"Status: {self.status}. Costs modeled: {self.costs_modeled}.\n"
            f"Trials logged prior to this result: {self.trials_logged}."
            f"  PBO: {self.pbo:.2f}."
            f"  LLM contamination verdict: {self.contamination_verdict}.\n"
            f"Limitations: {self.limitations}\n"
            "Results are from a single realized path of one strategy on one universe"
            " and should not be interpreted as evidence of a repeatable edge."
        )


@dataclass(frozen=True)
class ArtifactMetadata:
    """Metadata for a research artifact — used for methodology pinning."""

    git_commit: str
    config_hash: str
    seed: int
    snapshot_id: str
    uv_lock_hash: str = ""
    llm_model_version: str = ""
    prompt_version_hash: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Artifact:
    """A single research artifact with disclosure and metadata."""

    artifact_type: ArtifactType
    content: str
    metadata: ArtifactMetadata
    disclosure: DisclosureBlock
    dpi: int = 72  # Default; overridden to 300 for figures

    @property
    def content_hash(self) -> str:
        """SHA-256 of the content for reproducibility verification."""
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


def generate_artifact(
    artifact_type: ArtifactType,
    content: str,
    metadata: ArtifactMetadata,
    disclosure: DisclosureBlock,
) -> Artifact:
    """Generate a research artifact with disclosure block and correct DPI.

    Parameters
    ----------
    artifact_type : ArtifactType
        One of the seven recognized artifact types.
    content : str
        The artifact content (table text, figure spec, statistics, etc.).
    metadata : ArtifactMetadata
        Pinning metadata (git commit, config hash, seed, etc.).
    disclosure : DisclosureBlock
        Mandatory disclosure block (source, date, limitations).

    Returns
    -------
    Artifact
        Frozen dataclass with content, metadata, disclosure, and DPI setting.

    Raises
    ------
    ValueError
        If artifact_type is not a valid ArtifactType.
    """
    if not isinstance(artifact_type, ArtifactType):
        raise ValueError(
            f"Invalid artifact type: {artifact_type!r}. "
            f"Must be one of {[t.value for t in ArtifactType]}."
        )

    dpi = FIGURE_DPI if artifact_type == ArtifactType.FIGURES else 72

    return Artifact(
        artifact_type=artifact_type,
        content=content,
        metadata=metadata,
        disclosure=disclosure,
        dpi=dpi,
    )


def validate_artifact(artifact: Artifact) -> None:
    """Validate that an artifact has a complete disclosure block.

    Raises
    ------
    ValueError
        If any required disclosure field is empty or missing.
    """
    if not isinstance(artifact.disclosure, DisclosureBlock):
        raise ValueError("Artifact missing disclosure block.")

    required_fields = ["source", "date", "limitations"]
    for field_name in required_fields:
        value = getattr(artifact.disclosure, field_name, None)
        if not value or not value.strip():
            raise ValueError(
                f"Disclosure block field '{field_name}' is empty or missing."
            )

    if not isinstance(artifact.artifact_type, ArtifactType):
        raise ValueError(f"Invalid artifact type: {artifact.artifact_type!r}.")


def methodology_pins(artifacts: list[Artifact]) -> str:
    """Generate methodology.md content listing all pinned artifacts.

    Per docs/07 section 3 and docs/12 section 3: pins snapshot IDs, git commit,
    config hash, seeds, cost and impact assumptions, bootstrap method and block size,
    LLM model and prompt versions, contamination verdict, and trial count.

    Parameters
    ----------
    artifacts : list[Artifact]
        All artifacts to include in the methodology pinning.

    Returns
    -------
    str
        Deterministic methodology.md content.
    """
    if not artifacts:
        return "# Methodology\n\nNo artifacts generated.\n"

    # Sort artifacts deterministically by (type name, content hash) for byte-identical output.
    sorted_artifacts = sorted(
        artifacts, key=lambda a: (a.artifact_type.value, a.content_hash)
    )

    lines: list[str] = []
    lines.append("# Methodology")
    lines.append("")
    lines.append("## Pinned Artifacts")
    lines.append("")
    lines.append(f"Total artifacts: {len(sorted_artifacts)}")
    lines.append("")

    # Collect unique metadata for global pins.
    git_commits: set[str] = set()
    config_hashes: set[str] = set()
    seeds: list[int] = []
    snapshot_ids: set[str] = set()

    for art in sorted_artifacts:
        git_commits.add(art.metadata.git_commit)
        config_hashes.add(art.metadata.config_hash)
        seeds.append(art.metadata.seed)
        snapshot_ids.add(art.metadata.snapshot_id)

    lines.append("## Global Pins")
    lines.append("")
    lines.append(f"Git commits: {', '.join(sorted(git_commits))}")
    lines.append(f"Config hashes: {', '.join(sorted(config_hashes))}")
    lines.append(f"Seeds: {', '.join(str(s) for s in sorted(set(seeds)))}")
    lines.append(f"Snapshot IDs: {', '.join(sorted(snapshot_ids))}")
    lines.append("")

    # Per-artifact listing.
    lines.append("## Artifact Details")
    lines.append("")

    for art in sorted_artifacts:
        lines.append(f"### {art.artifact_type.value}")
        lines.append(f"- Content hash: {art.content_hash}")
        lines.append(f"- DPI: {art.dpi}")
        lines.append(f"- Git commit: {art.metadata.git_commit}")
        lines.append(f"- Config hash: {art.metadata.config_hash}")
        lines.append(f"- Seed: {art.metadata.seed}")
        lines.append(f"- Snapshot ID: {art.metadata.snapshot_id}")
        if art.metadata.uv_lock_hash:
            lines.append(f"- uv.lock hash: {art.metadata.uv_lock_hash}")
        if art.metadata.llm_model_version:
            lines.append(f"- LLM model version: {art.metadata.llm_model_version}")
        if art.metadata.prompt_version_hash:
            lines.append(f"- Prompt version hash: {art.metadata.prompt_version_hash}")
        lines.append(f"- Disclosure: {art.disclosure.render()}")
        lines.append("")

    return "\n".join(lines)


def _deterministic_serialize(artifact: Artifact) -> str:
    """Serialize an artifact deterministically for byte-identical regeneration.

    Uses sorted keys and stable formatting so the same inputs always produce
    the same byte sequence.
    """
    data = {
        "artifact_type": artifact.artifact_type.value,
        "content": artifact.content,
        "content_hash": artifact.content_hash,
        "dpi": artifact.dpi,
        "metadata": {
            "git_commit": artifact.metadata.git_commit,
            "config_hash": artifact.metadata.config_hash,
            "seed": artifact.metadata.seed,
            "snapshot_id": artifact.metadata.snapshot_id,
            "uv_lock_hash": artifact.metadata.uv_lock_hash,
            "llm_model_version": artifact.metadata.llm_model_version,
            "prompt_version_hash": artifact.metadata.prompt_version_hash,
            "extra": artifact.metadata.extra,
        },
        "disclosure": artifact.disclosure.render(),
    }
    return json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def regenerate_bytes(artifact: Artifact) -> bytes:
    """Produce the byte-identical output for a given artifact.

    Given the same inputs, this function always returns the exact same bytes.
    This is the contract that makes `make reproduce COMMIT=<hash>` possible.
    """
    return _deterministic_serialize(artifact).encode("utf-8")
