"""Tests for LLM filing extraction. TICKET-031."""

from __future__ import annotations

from datetime import date

import pytest

from durable.signals.extract import (
    AUDIT_SAMPLE_RATE,
    EXTRACTION_SCHEMA,
    PROMPT_VERSION,
    TEMPERATURE,
    CacheKey,
    ContaminationError,
    ExtractionField,
    ExtractionResult,
    ExtractedValue,
    check_contamination,
    extract_filing,
    make_cache_key,
    score_extraction,
    select_audit_sample,
    validate_extraction_response,
)


class TestFixedJsonSchema:
    """Fixed JSON schema — acceptance criterion."""

    def test_schema_has_required_fields(self):
        assert EXTRACTION_SCHEMA["type"] == "object"
        assert "ticker" in EXTRACTION_SCHEMA["properties"]
        assert "accession" in EXTRACTION_SCHEMA["properties"]
        assert "fields" in EXTRACTION_SCHEMA["properties"]

    def test_all_extraction_fields_in_schema(self):
        field_props = EXTRACTION_SCHEMA["properties"]["fields"]["properties"]
        for f in ExtractionField:
            assert f.value in field_props

    def test_each_field_has_required_subfields(self):
        field_props = EXTRACTION_SCHEMA["properties"]["fields"]["properties"]
        for f in ExtractionField:
            required = field_props[f.value]["properties"]
            assert "value" in required
            assert "citation" in required
            assert "section" in required
            assert "confidence" in required


class TestUncitedClaimsScoreZero:
    """Uncited claims score 0 — acceptance criterion."""

    def test_uncited_scores_zero(self):
        val = ExtractedValue(
            field=ExtractionField.REVENUE_GROWTH,
            value=0.15,
            citation=None,
            section=None,
            confidence="high",
        )
        assert score_extraction(val) == 0

    def test_empty_citation_scores_zero(self):
        val = ExtractedValue(
            field=ExtractionField.REVENUE_GROWTH,
            value=0.15,
            citation="",
            section="Item 7",
            confidence="high",
        )
        assert score_extraction(val) == 0

    def test_cited_scores_nonzero(self):
        val = ExtractedValue(
            field=ExtractionField.REVENUE_GROWTH,
            value=0.15,
            citation="0001234567-24-000123",
            section="Item 7",
            confidence="high",
        )
        assert score_extraction(val) == 1

    def test_extraction_result_separates_cited(self):
        values = [
            ExtractedValue(ExtractionField.REVENUE_GROWTH, 0.1, "acc-1", "7", "high"),
            ExtractedValue(ExtractionField.ROIC, 0.12, None, None, "high"),
        ]
        result = ExtractionResult(
            ticker="TEST", accession="acc", available_at=date(2025, 1, 1),
            model_version="v1", prompt_version="v1.0", temperature=0,
            values=values, cache_key=CacheKey("acc", "v1.0", "v1"),
        )
        assert len(result.cited_values) == 1
        assert len(result.uncited_values) == 1


class TestCaching:
    """Cached by (accession, prompt_version, model_version) — acceptance criterion."""

    def test_cache_key_structure(self):
        key = make_cache_key("0001234567-24-000123", "v1.0", "claude-3.5")
        assert key.accession == "0001234567-24-000123"
        assert key.prompt_version == "v1.0"
        assert key.model_version == "claude-3.5"

    def test_cache_hit_skips_extraction(self):
        cache: dict[CacheKey, ExtractionResult] = {}
        call_count = [0]

        def mock_llm(text, schema, temp):
            call_count[0] += 1
            return {"ticker": "X", "accession": "acc", "fields": {}}

        extract_filing(
            "TEST", "acc", "text", date(2025, 6, 1),
            "claude-3.5", date(2024, 1, 1),
            llm_callable=mock_llm, allow_contaminated=True, cache=cache,
        )
        assert call_count[0] == 1

        extract_filing(
            "TEST", "acc", "text", date(2025, 6, 1),
            "claude-3.5", date(2024, 1, 1),
            llm_callable=mock_llm, allow_contaminated=True, cache=cache,
        )
        assert call_count[0] == 1  # Cache hit, no second call

    def test_different_model_version_cache_miss(self):
        key1 = make_cache_key("acc", "v1.0", "claude-3.5")
        key2 = make_cache_key("acc", "v1.0", "claude-4.0")
        assert key1 != key2


class TestAvailableAtFromFiling:
    """available_at from the filing — acceptance criterion."""

    def test_available_at_is_filing_date(self):
        filing_date = date(2025, 3, 15)
        result = extract_filing(
            "TEST", "acc", "text", filing_date,
            "claude-3.5", date(2024, 1, 1),
            allow_contaminated=True,
        )
        assert result.available_at == filing_date


class TestTemperatureZero:
    """Temperature 0 — acceptance criterion."""

    def test_temperature_constant(self):
        assert TEMPERATURE == 0

    def test_result_records_temperature(self):
        result = extract_filing(
            "TEST", "acc", "text", date(2025, 6, 1),
            "claude-3.5", date(2024, 1, 1),
            allow_contaminated=True,
        )
        assert result.temperature == 0


class TestLowConfidenceNull:
    """Low confidence => null — acceptance criterion."""

    def test_low_confidence_becomes_none(self):
        response = {
            "fields": {
                "revenue_growth": {
                    "value": 0.15,
                    "citation": "acc-123",
                    "section": "Item 7",
                    "confidence": "low",
                },
            },
        }
        values = validate_extraction_response(response)
        rev = next(v for v in values if v.field == ExtractionField.REVENUE_GROWTH)
        assert rev.value is None  # Low confidence => null

    def test_high_confidence_preserved(self):
        response = {
            "fields": {
                "revenue_growth": {
                    "value": 0.15,
                    "citation": "acc-123",
                    "section": "Item 7",
                    "confidence": "high",
                },
            },
        }
        values = validate_extraction_response(response)
        rev = next(v for v in values if v.field == ExtractionField.REVENUE_GROWTH)
        assert rev.value == 0.15


class TestContaminationGuard:
    """Contamination guard raises — acceptance criterion."""

    def test_raises_when_before_cutoff(self):
        with pytest.raises(ContaminationError, match="before model training cutoff"):
            check_contamination(
                filing_date=date(2023, 6, 1),
                model_training_cutoff=date(2024, 1, 1),
                allow_contaminated=False,
            )

    def test_does_not_raise_with_allow_flag(self):
        result = check_contamination(
            filing_date=date(2023, 6, 1),
            model_training_cutoff=date(2024, 1, 1),
            allow_contaminated=True,
        )
        assert result is True  # Is contaminated

    def test_no_contamination_after_cutoff(self):
        result = check_contamination(
            filing_date=date(2025, 6, 1),
            model_training_cutoff=date(2024, 1, 1),
        )
        assert result is False

    def test_extract_filing_raises_on_contamination(self):
        with pytest.raises(ContaminationError):
            extract_filing(
                "TEST", "acc", "text", date(2023, 1, 1),
                "claude-3.5", date(2024, 1, 1),
                allow_contaminated=False,
            )

    def test_contaminated_result_tagged(self):
        result = extract_filing(
            "TEST", "acc", "text", date(2023, 1, 1),
            "claude-3.5", date(2024, 1, 1),
            allow_contaminated=True,
        )
        assert result.contaminated is True


class TestAuditSample:
    """audit_sample(0.10) — acceptance criterion."""

    def test_sample_rate_constant(self):
        assert AUDIT_SAMPLE_RATE == 0.10

    def test_selects_10_percent(self):
        extractions = [
            ExtractionResult(
                ticker=f"T{i}", accession=f"acc{i}", available_at=date(2025, 1, 1),
                model_version="v1", prompt_version="v1.0", temperature=0,
                values=[], cache_key=CacheKey(f"acc{i}", "v1.0", "v1"),
            )
            for i in range(100)
        ]
        sample = select_audit_sample(extractions, rate=0.10, seed=42)
        assert len(sample) == 10

    def test_deterministic_with_seed(self):
        extractions = [
            ExtractionResult(
                ticker=f"T{i}", accession=f"acc{i}", available_at=date(2025, 1, 1),
                model_version="v1", prompt_version="v1.0", temperature=0,
                values=[], cache_key=CacheKey(f"acc{i}", "v1.0", "v1"),
            )
            for i in range(50)
        ]
        sample1 = select_audit_sample(extractions, seed=42)
        sample2 = select_audit_sample(extractions, seed=42)
        assert [s.ticker for s in sample1] == [s.ticker for s in sample2]

    def test_minimum_one_sample(self):
        extractions = [
            ExtractionResult(
                ticker="ONLY", accession="acc", available_at=date(2025, 1, 1),
                model_version="v1", prompt_version="v1.0", temperature=0,
                values=[], cache_key=CacheKey("acc", "v1.0", "v1"),
            )
        ]
        sample = select_audit_sample(extractions)
        assert len(sample) == 1
