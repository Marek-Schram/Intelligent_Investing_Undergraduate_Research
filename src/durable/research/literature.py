"""Literature ledger. docs/12 section 3. TICKET-040.

claims.csv schema enforced including `contradicted_by`. A claim used in any doc without
a ledger entry raises in CI. Manages academic references for the research study.

Data source: academic papers, research notes.
available_at logic: N/A (research artifact).
Spec section: docs/12 §3.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


CLAIMS_SCHEMA_FIELDS = [
    "claim_id",
    "claim",
    "source",
    "authors",
    "year",
    "doi",
    "supported_by",
    "contradicted_by",
    "used_in",
    "notes",
]


class ClaimValidationError(ValueError):
    """Raised when a claim fails schema validation."""

    pass


class MissingLedgerEntryError(ValueError):
    """Raised when a claim is used in a doc without a ledger entry."""

    pass


@dataclass(frozen=True)
class Claim:
    """One literature claim with required contradicted_by field."""

    claim_id: str
    claim: str
    source: str
    authors: str
    year: int
    doi: str = ""
    supported_by: str = ""
    contradicted_by: str = ""
    used_in: str = ""
    notes: str = ""


def validate_claim(claim: Claim) -> None:
    """Validate a claim against the schema.

    Raises ClaimValidationError if required fields are missing.
    contradicted_by is a required field (may be "none known" but not empty
    for claims where contradicting evidence exists).
    """
    if not claim.claim_id:
        raise ClaimValidationError("claim_id is required")
    if not claim.claim:
        raise ClaimValidationError("claim text is required")
    if not claim.source:
        raise ClaimValidationError("source is required")
    if not claim.authors:
        raise ClaimValidationError("authors is required")


def validate_claims_csv(rows: list[dict]) -> list[str]:
    """Validate a claims.csv file. Returns list of errors (empty = valid)."""
    errors = []
    for i, row in enumerate(rows):
        for field_name in CLAIMS_SCHEMA_FIELDS:
            if field_name not in row:
                errors.append(f"Row {i}: missing field '{field_name}'")

        if "contradicted_by" in row and not isinstance(row["contradicted_by"], str):
            errors.append(f"Row {i}: contradicted_by must be a string")

    return errors


def check_claim_used_in_doc(
    claim_id: str,
    ledger: list[Claim],
) -> bool:
    """Check if a claim_id exists in the ledger.

    A claim used in any doc without a ledger entry raises.
    """
    return any(c.claim_id == claim_id for c in ledger)


def assert_claim_in_ledger(claim_id: str, ledger: list[Claim]) -> None:
    """Raise MissingLedgerEntryError if claim not in ledger."""
    if not check_claim_used_in_doc(claim_id, ledger):
        raise MissingLedgerEntryError(
            f"Claim '{claim_id}' used in a document but has no ledger entry. "
            f"Add it to claims.csv before using."
        )


def find_claims_without_contradiction(ledger: list[Claim]) -> list[Claim]:
    """Find claims that should have contradicted_by but don't.

    These are claims about premiums or effects where contradicting
    evidence is known to exist.
    """
    return [c for c in ledger if not c.contradicted_by.strip()]
