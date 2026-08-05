"""LLM filing extraction. docs/10 section 1. TICKET-031.

Extraction, never prediction. Fixed JSON schema. Citation required or score=0.
Temperature 0. Low confidence => null. Cached by (accession, prompt_version, model_version).
available_at from the filing acceptance date, not the extraction run.

Contamination guard raises ContaminationError unless allow_contaminated=True.
audit_sample(0.10) writes to extraction_audit.csv for quarterly review.

Data source: SEC EDGAR filings via PIT store.
available_at logic: inherited from the filing's acceptance datetime.
Spec section: docs/10 §1.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
The actual LLM call is injected as a callable; this module handles schema, caching,
validation, and audit logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any


PROMPT_VERSION = "v1.0"
TEMPERATURE = 0
AUDIT_SAMPLE_RATE = 0.10


class ContaminationError(Exception):
    """Raised when extraction is used in a backtest window before model training cutoff."""

    pass


class ExtractionField(Enum):
    REVENUE_GROWTH = "revenue_growth"
    OPERATING_MARGIN = "operating_margin"
    ROIC = "roic"
    FCF_YIELD = "fcf_yield"
    DEBT_TO_EBITDA = "debt_to_ebitda"
    CUSTOMER_CONCENTRATION = "customer_concentration"
    RECURRING_REVENUE_PCT = "recurring_revenue_pct"
    CAPEX_TO_REVENUE = "capex_to_revenue"
    INSIDER_OWNERSHIP_PCT = "insider_ownership_pct"
    RD_TO_REVENUE = "rd_to_revenue"


EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "ticker": {"type": "string"},
        "accession": {"type": "string"},
        "fields": {
            "type": "object",
            "properties": {
                f.value: {
                    "type": "object",
                    "properties": {
                        "value": {"type": ["number", "null"]},
                        "citation": {"type": ["string", "null"]},
                        "section": {"type": ["string", "null"]},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    },
                    "required": ["value", "citation", "section", "confidence"],
                }
                for f in ExtractionField
            },
        },
    },
    "required": ["ticker", "accession", "fields"],
}


@dataclass(frozen=True)
class ExtractedValue:
    """One extracted value with citation."""

    field: ExtractionField
    value: float | None
    citation: str | None
    section: str | None
    confidence: str
    score: int = 0

    @property
    def is_cited(self) -> bool:
        return self.citation is not None and len(self.citation.strip()) > 0

    @property
    def is_valid(self) -> bool:
        return self.value is not None and self.confidence != "low"


@dataclass(frozen=True)
class CacheKey:
    """Cache key for extraction results."""

    accession: str
    prompt_version: str
    model_version: str


@dataclass
class ExtractionResult:
    """Full extraction result from a filing."""

    ticker: str
    accession: str
    available_at: date
    model_version: str
    prompt_version: str
    temperature: int
    values: list[ExtractedValue]
    cache_key: CacheKey
    contaminated: bool = False

    @property
    def cited_values(self) -> list[ExtractedValue]:
        return [v for v in self.values if v.is_cited]

    @property
    def uncited_values(self) -> list[ExtractedValue]:
        return [v for v in self.values if not v.is_cited]


def score_extraction(value: ExtractedValue) -> int:
    """Score a single extracted value. Uncited claims score 0."""
    if not value.is_cited:
        return 0
    if value.confidence == "low":
        return 0
    if value.value is None:
        return 0
    return 1


def validate_extraction_response(response: dict) -> list[ExtractedValue]:
    """Validate and convert a raw LLM response into ExtractedValue objects.

    Low confidence => value becomes None (null). Uncited claims retained but score 0.
    """
    fields_data = response.get("fields", {})
    results = []

    for field_enum in ExtractionField:
        field_data = fields_data.get(field_enum.value)
        if field_data is None:
            results.append(ExtractedValue(
                field=field_enum,
                value=None,
                citation=None,
                section=None,
                confidence="low",
            ))
            continue

        confidence = field_data.get("confidence", "low")
        value = field_data.get("value")
        citation = field_data.get("citation")
        section = field_data.get("section")

        if confidence == "low":
            value = None

        extracted = ExtractedValue(
            field=field_enum,
            value=value,
            citation=citation,
            section=section,
            confidence=confidence,
            score=0,
        )
        results.append(extracted)

    return results


def check_contamination(
    filing_date: date,
    model_training_cutoff: date,
    allow_contaminated: bool = False,
) -> bool:
    """Check if extraction might be contaminated.

    Raises ContaminationError unless allow_contaminated=True.
    Returns True if contaminated (filing is before model training cutoff).
    """
    is_contaminated = filing_date < model_training_cutoff

    if is_contaminated and not allow_contaminated:
        raise ContaminationError(
            f"Filing date {filing_date} is before model training cutoff "
            f"{model_training_cutoff}. Pass allow_contaminated=True to proceed "
            f"(results will be tagged CONTAMINATED)."
        )

    return is_contaminated


def make_cache_key(
    accession: str,
    prompt_version: str = PROMPT_VERSION,
    model_version: str = "",
) -> CacheKey:
    """Create cache key from (accession, prompt_version, model_version)."""
    return CacheKey(
        accession=accession,
        prompt_version=prompt_version,
        model_version=model_version,
    )


def extract_filing(
    ticker: str,
    accession: str,
    filing_text: str,
    filing_acceptance_date: date,
    model_version: str,
    model_training_cutoff: date,
    llm_callable: Any = None,
    allow_contaminated: bool = False,
    cache: dict[CacheKey, ExtractionResult] | None = None,
) -> ExtractionResult:
    """Extract structured data from a filing using LLM.

    available_at = filing_acceptance_date (NOT when the extraction ran).
    Temperature = 0. Low confidence => null.
    Cached by (accession, prompt_version, model_version).
    """
    cache_key = make_cache_key(accession, PROMPT_VERSION, model_version)

    if cache is not None and cache_key in cache:
        return cache[cache_key]

    is_contaminated = check_contamination(
        filing_acceptance_date, model_training_cutoff, allow_contaminated
    )

    if llm_callable is None:
        values = validate_extraction_response({"fields": {}})
    else:
        raw_response = llm_callable(filing_text, EXTRACTION_SCHEMA, TEMPERATURE)
        values = validate_extraction_response(raw_response)

    scored_values = []
    for v in values:
        s = score_extraction(v)
        scored_values.append(ExtractedValue(
            field=v.field,
            value=v.value,
            citation=v.citation,
            section=v.section,
            confidence=v.confidence,
            score=s,
        ))

    result = ExtractionResult(
        ticker=ticker,
        accession=accession,
        available_at=filing_acceptance_date,
        model_version=model_version,
        prompt_version=PROMPT_VERSION,
        temperature=TEMPERATURE,
        values=scored_values,
        cache_key=cache_key,
        contaminated=is_contaminated,
    )

    if cache is not None:
        cache[cache_key] = result

    return result


def select_audit_sample(
    extractions: list[ExtractionResult],
    rate: float = AUDIT_SAMPLE_RATE,
    seed: int = 42,
) -> list[ExtractionResult]:
    """Select a random sample for quarterly audit.

    Writes to extraction_audit.csv (handled by caller).
    Returns the selected extractions.
    """
    import random

    rng = random.Random(seed)
    n_sample = max(1, int(len(extractions) * rate))
    if n_sample >= len(extractions):
        return list(extractions)
    return rng.sample(extractions, n_sample)
