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

The one deliberate exception is `main()` / the `--ticker` CLI at the bottom of this file: it
is the orchestration layer that supplies the injected `llm_callable` for standalone use
(fetches a filing, calls the Anthropic API, writes a JSON result). It performs exactly the
I/O the functions above are written to avoid, and nothing above it was changed to add it.
The interactive alternative is the extract-filing skill (.claude/skills/extract-filing/),
which needs no API key of its own.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dotenv import load_dotenv

from durable.config import PROJECT_ROOT, ConfigError, load_config
from durable.data.sec import fetch_latest_filing

if TYPE_CHECKING:
    from collections.abc import Sequence

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
            results.append(
                ExtractedValue(
                    field=field_enum,
                    value=None,
                    citation=None,
                    section=None,
                    confidence="low",
                )
            )
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

    A filing dated before the model's training cutoff means the model was trained
    on data from that period - it has "read the future" relative to a backtest
    using that filing.
    """
    is_contaminated = filing_date < model_training_cutoff

    if is_contaminated and not allow_contaminated:
        raise ContaminationError(
            f"Filing date {filing_date} is before model training cutoff "
            f"{model_training_cutoff}. The model was trained on this period - "
            f"using this extraction in a backtest is contaminated. "
            f"Pass allow_contaminated=True to proceed (results will be tagged CONTAMINATED)."
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
        scored_values.append(
            ExtractedValue(
                field=v.field,
                value=v.value,
                citation=v.citation,
                section=v.section,
                confidence=v.confidence,
                score=s,
            )
        )

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


# --------------------------------------------------------------------------------------
# CLI: `make extract TICKER=XYZ` / `python -m durable.signals.extract --ticker XYZ`.
# See the module docstring: this is the one place in the file that does I/O.
# --------------------------------------------------------------------------------------


def _build_prompt(filing_text: str) -> str:
    """Build the extraction prompt. Filing text is capped to a fixed character budget so a
    single request stays within a predictable context size; truncation is disclosed to the
    model so it reports missing sections as low-confidence rather than guessing."""
    max_chars = 180_000
    body = filing_text[:max_chars]
    truncated_note = ""
    if len(filing_text) > max_chars:
        truncated_note = (
            f"\n\n[NOTE: filing text truncated to {max_chars} of {len(filing_text)} total "
            "characters. If a field's supporting section was not included above, report it "
            "as low confidence with a null value -- never guess.]"
        )
    field_list = ", ".join(f.value for f in ExtractionField)
    return (
        "You are extracting structured facts from an SEC filing for a long-horizon equity "
        "research system. This is extraction, not prediction: never estimate a price, "
        "return, or rating -- only report what the filing text explicitly states.\n\n"
        f"Extract these fields: {field_list}.\n"
        "For each field, report `value` (a number, or null if unsupported), `citation` "
        "(an exact quote or precise section reference from the text below -- required "
        "whenever value is not null), `section` (e.g. 'Item 7'), and `confidence` "
        "('high', 'medium', or 'low'). If you cannot find explicit support in the text, "
        "set value to null and confidence to 'low'. Never guess a number.\n\n"
        f"--- FILING TEXT ---\n{body}{truncated_note}"
    )


def _make_anthropic_llm_callable(api_key: str, model: str):
    """Build the llm_callable injected into extract_filing(). Uses tool-forced structured
    output (Anthropic tool-use with EXTRACTION_SCHEMA as the tool's input_schema) so the
    response conforms to the fixed JSON schema without parsing a number out of free text."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    tool_name = "record_filing_extraction"

    def _call(filing_text: str, schema: dict, temperature: int) -> dict:
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            temperature=temperature,
            tools=[
                {
                    "name": tool_name,
                    "description": "Record the structured extraction result for one filing.",
                    "input_schema": schema,
                }
            ],
            tool_choice={"type": "tool", "name": tool_name},
            messages=[{"role": "user", "content": _build_prompt(filing_text)}],
        )
        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
                return block.input
        raise RuntimeError(
            f"Anthropic response did not include the expected tool_use block ({tool_name}); "
            f"got content types: {[getattr(b, 'type', None) for b in response.content]}"
        )

    return _call


def _write_extraction_json(result: ExtractionResult, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{result.ticker}_{result.accession}.json"
    payload = {
        "ticker": result.ticker,
        "accession": result.accession,
        "available_at": result.available_at.isoformat(),
        "model_version": result.model_version,
        "prompt_version": result.prompt_version,
        "temperature": result.temperature,
        "contaminated": result.contaminated,
        "fields": {
            v.field.value: {
                "value": v.value,
                "citation": v.citation,
                "section": v.section,
                "confidence": v.confidence,
                "score": v.score,
            }
            for v in result.values
        },
    }
    out_path.write_text(json.dumps(payload, indent=2))
    return out_path


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(description="LLM filing extraction for one ticker.")
    parser.add_argument("--ticker", required=True, help="Ticker to extract, e.g. AAPL")
    parser.add_argument(
        "--allow-contaminated",
        action="store_true",
        help="Proceed even if the filing predates the model's training cutoff. Results are "
        "tagged CONTAMINATED -- see .claude/rules/llm-extraction.md rule 7.",
    )
    parser.add_argument(
        "--form-types",
        default="10-K,10-Q",
        help="Comma-separated SEC form types to search; most recent wins (default: 10-K,10-Q)",
    )
    args = parser.parse_args(argv)

    ticker = args.ticker.strip().upper()
    form_types = tuple(t.strip() for t in args.form_types.split(",") if t.strip())

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "ANTHROPIC_API_KEY is not set. This standalone CLI calls the Anthropic API "
            "directly and needs a key in .env (see .env.example).\n"
            "Extraction is also designed to run interactively inside a Claude Code session "
            "using the extract-filing skill instead -- see "
            ".claude/skills/extract-filing/SKILL.md -- which needs no API key of its own."
        )
        return 1

    identity = os.getenv("EDGAR_IDENTITY")
    if not identity:
        print(
            "EDGAR_IDENTITY is not set. SEC EDGAR requires a descriptive identity string "
            "('Your Name your.email@example.com') on every request. Set it in .env "
            "(see .env.example) before fetching filing text."
        )
        return 1

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}")
        return 1

    llm_cfg = config.get("signals", {}).get("llm_extraction", {})
    model_version = llm_cfg.get("model")
    cutoff_str = llm_cfg.get("model_training_cutoff")
    if not model_version or not cutoff_str:
        print(
            "config/config.yaml is missing signals.llm_extraction.model or "
            "model_training_cutoff -- both are required (the cutoff gates the contamination "
            "check in llm-extraction.md rule 7)."
        )
        return 1
    model_training_cutoff = date.fromisoformat(cutoff_str)

    try:
        filing = fetch_latest_filing(ticker, identity, form_types)
    except Exception as exc:  # noqa: BLE001 - report, don't dump a raw traceback
        print(f"Could not fetch a filing for {ticker}: {type(exc).__name__}: {exc}")
        return 1

    llm_callable = _make_anthropic_llm_callable(api_key, model_version)

    try:
        result = extract_filing(
            ticker=ticker,
            accession=filing.accession,
            filing_text=filing.text,
            filing_acceptance_date=filing.available_at.date(),
            model_version=model_version,
            model_training_cutoff=model_training_cutoff,
            llm_callable=llm_callable,
            allow_contaminated=args.allow_contaminated,
        )
    except ContaminationError:
        # Deliberately NOT swallowed: surfaces with its own message so a contaminated
        # extraction can never be silently folded into a backtest. --allow-contaminated is
        # the explicit opt-in (llm-extraction.md rule 7).
        raise
    except Exception as exc:  # noqa: BLE001 - vendor/network errors, report cleanly
        print(f"Extraction failed for {ticker} ({filing.accession}): {type(exc).__name__}: {exc}")
        return 1

    out_dir = PROJECT_ROOT / "data" / "processed" / "extractions"
    out_path = _write_extraction_json(result, out_dir)

    n_cited = len(result.cited_values)
    n_total = len(result.values)
    print(
        f"Extracted {ticker} {filing.form} ({filing.accession}): {n_cited}/{n_total} fields "
        f"cited. Contaminated={result.contaminated}. Wrote {out_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
