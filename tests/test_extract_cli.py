"""Tests for the `--ticker` extraction CLI added to signals/extract.py. TICKET-031.

These cover only the NEW orchestration code (prompt building, JSON writing, credential
gating, and the contamination guard actually propagating out of main()) -- not the pure
schema/scoring/caching functions in extract.py, which already have tests in
tests/test_extraction.py. No test here calls the real Anthropic API or SEC EDGAR: the I/O
boundaries (fetch_latest_filing, the Anthropic callable factory, the JSON writer) are
monkeypatched.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pytest

from durable.signals import extract as extract_module
from durable.signals.extract import (
    CacheKey,
    ContaminationError,
    ExtractedValue,
    ExtractionField,
    ExtractionResult,
    _build_prompt,
    _write_extraction_json,
    main,
)


@dataclass
class FakeFiling:
    ticker: str
    accession: str
    form: str
    filing_date: date
    acceptance_datetime: datetime | None
    available_at: datetime
    text: str


class TestBuildPrompt:
    def test_includes_every_field_name_and_no_truncation_note_for_short_text(self):
        prompt = _build_prompt("short filing text")
        for f in ExtractionField:
            assert f.value in prompt
        assert "TRUNCATED" not in prompt.upper() or "truncated" not in prompt
        assert "short filing text" in prompt

    def test_truncates_long_text_and_notes_it(self):
        long_text = "x" * 200_000
        prompt = _build_prompt(long_text)
        # Body is capped to 180_000 chars; the note explains the truncation. Checked by
        # substring (not a raw "x" count) since the surrounding instructions legitimately
        # contain the letter x (e.g. "extraction", "exact").
        assert "truncated to 180000 of 200000" in prompt
        assert ("x" * 180_000) in prompt
        assert ("x" * 200_000) not in prompt


class TestWriteExtractionJson:
    def test_writes_hand_computed_payload(self, tmp_path):
        values = [
            ExtractedValue(
                field=ExtractionField.REVENUE_GROWTH,
                value=0.12,
                citation="0001234567-24-000123, Item 7",
                section="Item 7",
                confidence="high",
                score=1,
            ),
            ExtractedValue(
                field=ExtractionField.ROIC,
                value=None,
                citation=None,
                section=None,
                confidence="low",
                score=0,
            ),
        ]
        result = ExtractionResult(
            ticker="TEST",
            accession="0001234567-24-000123",
            available_at=date(2024, 3, 15),
            model_version="claude-test",
            prompt_version="v1.0",
            temperature=0,
            values=values,
            cache_key=CacheKey("0001234567-24-000123", "v1.0", "claude-test"),
            contaminated=False,
        )

        out_path = _write_extraction_json(result, tmp_path)

        assert out_path == tmp_path / "TEST_0001234567-24-000123.json"
        payload = json.loads(out_path.read_text())
        assert payload["ticker"] == "TEST"
        assert payload["accession"] == "0001234567-24-000123"
        assert payload["available_at"] == "2024-03-15"
        assert payload["contaminated"] is False
        assert payload["fields"]["revenue_growth"] == {
            "value": 0.12,
            "citation": "0001234567-24-000123, Item 7",
            "section": "Item 7",
            "confidence": "high",
            "score": 1,
        }
        assert payload["fields"]["roic"]["value"] is None
        assert payload["fields"]["roic"]["score"] == 0


class TestMainCredentialGating:
    # setenv("", ...) rather than delenv(): main() calls load_dotenv(), which never
    # overrides a key already present in os.environ (even an empty one), so this is what
    # actually blocks a real local .env from leaking real credentials into these tests.
    def test_missing_anthropic_key_exits_1_and_points_at_skill(self, monkeypatch, capsys):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        exit_code = main(["--ticker", "AAPL"])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "ANTHROPIC_API_KEY" in captured.out
        assert ".claude/skills/extract-filing/SKILL.md" in captured.out

    def test_missing_edgar_identity_exits_1(self, monkeypatch, capsys):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
        monkeypatch.setenv("EDGAR_IDENTITY", "")
        exit_code = main(["--ticker", "AAPL"])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "EDGAR_IDENTITY" in captured.out


class TestMainContaminationGuard:
    def test_contamination_error_propagates_uncaught_without_allow_flag(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
        monkeypatch.setenv("EDGAR_IDENTITY", "Test Name test@example.com")
        monkeypatch.setattr(
            extract_module,
            "load_config",
            lambda: {
                "signals": {
                    "llm_extraction": {
                        "model": "claude-test-model",
                        "model_training_cutoff": "2024-01-01",
                    }
                }
            },
        )
        old_filing = FakeFiling(
            ticker="TEST",
            accession="acc-old",
            form="10-K",
            filing_date=date(2023, 5, 1),
            acceptance_datetime=datetime(2023, 5, 1, 16, 0, 0),
            available_at=datetime(2023, 5, 2, 9, 30, 0),  # before the 2024-01-01 cutoff
            text="some filing text",
        )
        monkeypatch.setattr(
            extract_module, "fetch_latest_filing", lambda ticker, identity, forms: old_filing
        )

        def _llm_callable_that_must_not_run(*args, **kwargs):
            pytest.fail("the LLM must never actually be called before the contamination guard")

        # Building the callable (constructing an API client) is harmless and does happen
        # before extract_filing()'s internal check_contamination() call; what must never
        # happen is *invoking* it, which is what this fixture actually asserts.
        monkeypatch.setattr(
            extract_module,
            "_make_anthropic_llm_callable",
            lambda api_key, model: _llm_callable_that_must_not_run,
        )

        with pytest.raises(ContaminationError, match="before model training cutoff"):
            main(["--ticker", "TEST"])


class TestMainSuccessfulRun:
    def test_writes_extraction_and_returns_0(self, monkeypatch, capsys):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
        monkeypatch.setenv("EDGAR_IDENTITY", "Test Name test@example.com")
        monkeypatch.setattr(
            extract_module,
            "load_config",
            lambda: {
                "signals": {
                    "llm_extraction": {
                        "model": "claude-test-model",
                        "model_training_cutoff": "2024-01-01",
                    }
                }
            },
        )
        new_filing = FakeFiling(
            ticker="TEST",
            accession="acc-new",
            form="10-Q",
            filing_date=date(2025, 5, 1),
            acceptance_datetime=datetime(2025, 5, 1, 16, 0, 0),
            available_at=datetime(2025, 5, 2, 9, 30, 0),
            text="some filing text",
        )
        monkeypatch.setattr(
            extract_module, "fetch_latest_filing", lambda ticker, identity, forms: new_filing
        )

        def fake_llm(filing_text: str, schema: dict, temperature: int) -> dict:
            return {
                "ticker": "TEST",
                "accession": "acc-new",
                "fields": {
                    "revenue_growth": {
                        "value": 0.2,
                        "citation": "acc-new, Item 7",
                        "section": "Item 7",
                        "confidence": "high",
                    }
                },
            }

        monkeypatch.setattr(
            extract_module, "_make_anthropic_llm_callable", lambda api_key, model: fake_llm
        )

        written: dict = {}

        def fake_write(result, out_dir):
            written["result"] = result
            written["out_dir"] = out_dir
            return Path("/fake/TEST_acc-new.json")

        monkeypatch.setattr(extract_module, "_write_extraction_json", fake_write)

        exit_code = main(["--ticker", "test"])  # lowercase input, must be upper-cased

        assert exit_code == 0
        assert written["result"].ticker == "TEST"
        assert written["result"].contaminated is False
        assert (
            written["out_dir"]
            == extract_module.PROJECT_ROOT / "data" / "processed" / "extractions"
        )

        captured = capsys.readouterr()
        assert "Extracted TEST 10-Q (acc-new): 1/10 fields cited" in captured.out
        assert "Wrote /fake/TEST_acc-new.json" in captured.out
