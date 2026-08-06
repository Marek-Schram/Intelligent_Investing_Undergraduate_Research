"""Tests for literature ledger. TICKET-040."""

from __future__ import annotations

import pytest

from durable.research.literature import (
    CLAIMS_SCHEMA_FIELDS,
    Claim,
    ClaimValidationError,
    MissingLedgerEntryError,
    assert_claim_in_ledger,
    check_claim_used_in_doc,
    find_claims_without_contradiction,
    validate_claim,
    validate_claims_csv,
)


class TestClaimsSchema:
    """claims.csv schema enforced — acceptance criterion."""

    def test_schema_has_contradicted_by(self):
        """contradicted_by is a required schema field."""
        assert "contradicted_by" in CLAIMS_SCHEMA_FIELDS

    def test_all_required_fields(self):
        expected = {
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
        }
        assert set(CLAIMS_SCHEMA_FIELDS) == expected

    def test_valid_row_passes(self):
        row = {f: "test" for f in CLAIMS_SCHEMA_FIELDS}
        errors = validate_claims_csv([row])
        assert errors == []

    def test_missing_field_fails(self):
        row = {"claim_id": "C1", "claim": "test"}
        errors = validate_claims_csv([row])
        assert len(errors) > 0


class TestContradictedBy:
    """contradicted_by field enforced — acceptance criterion."""

    def test_find_claims_without_contradiction(self):
        ledger = [
            Claim(
                "C1",
                "Neglect premium exists",
                "Arbel 1982",
                "Arbel",
                1982,
                contradicted_by="Beard & Sias 1997",
            ),
            Claim(
                "C2", "Small-cap premium", "Banz 1981", "Banz", 1981, contradicted_by=""
            ),  # Missing!
        ]
        missing = find_claims_without_contradiction(ledger)
        assert len(missing) == 1
        assert missing[0].claim_id == "C2"


class TestClaimUsedWithoutLedger:
    """Claim used in doc without ledger entry raises — acceptance criterion."""

    def test_missing_raises(self):
        ledger = [Claim("C1", "test", "src", "auth", 2020)]
        with pytest.raises(MissingLedgerEntryError):
            assert_claim_in_ledger("C99", ledger)

    def test_present_passes(self):
        ledger = [Claim("C1", "test", "src", "auth", 2020)]
        assert_claim_in_ledger("C1", ledger)  # No raise

    def test_check_returns_bool(self):
        ledger = [Claim("C1", "test", "src", "auth", 2020)]
        assert check_claim_used_in_doc("C1", ledger) is True
        assert check_claim_used_in_doc("C99", ledger) is False


class TestValidation:
    def test_missing_claim_id(self):
        with pytest.raises(ClaimValidationError):
            validate_claim(Claim("", "text", "src", "auth", 2020))

    def test_valid_claim(self):
        claim = Claim("C1", "text", "src", "auth", 2020)
        validate_claim(claim)  # No raise
