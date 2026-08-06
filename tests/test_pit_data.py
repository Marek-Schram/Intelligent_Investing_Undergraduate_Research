"""Regression tests for durable.discovery.pit_data's annual-series helpers.

Focused on a real bug found running the CLI against freshly-ingested data: a ticker with
operating_cash_flow but no capex field (a legitimate, common case -- not every filing tags
every concept) crashed `_fcf_annual`'s merge with `KeyError: '_year'`, because
`_annual_values`'s empty-input early return didn't include the `_year` column the merge
needs. Hand-computed fixtures, not golden files.
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from durable.discovery.pit_data import _annual_values, _cagr, _fcf_annual


def _facts_rows(field: str, values: list[tuple[date, float]]) -> list[dict]:
    return [
        {
            "ticker": "T",
            "field": field,
            "period_end": period_end,
            "value": value,
            "filed_at": datetime(period_end.year, period_end.month, period_end.day),
            "available_at": datetime(period_end.year, period_end.month, period_end.day),
            "accession": f"acc-{period_end}",
            "restated": False,
        }
        for period_end, value in values
    ]


class TestAnnualValuesEmptyInput:
    def test_missing_field_returns_empty_frame_with_year_column(self):
        """The exact shape _fcf_annual's merge needs, even with zero rows."""
        facts = pd.DataFrame(_facts_rows("operating_cash_flow", [(date(2023, 12, 31), 100.0)]))
        result = _annual_values(facts, "capex")  # "capex" field not present at all
        assert result.empty
        assert "_year" in result.columns
        assert "value" in result.columns

    def test_present_field_collapses_to_one_row_per_year(self):
        facts = pd.DataFrame(
            _facts_rows(
                "revenue",
                [
                    (date(2022, 3, 31), 10.0),  # superseded by the later 2022 report
                    (date(2022, 12, 31), 40.0),
                    (date(2023, 12, 31), 50.0),
                ],
            )
        )
        result = _annual_values(facts, "revenue")
        assert list(result["value"]) == [40.0, 50.0]


class TestFcfAnnualMissingCapex:
    def test_missing_capex_field_does_not_raise_and_uses_zero(self):
        """FCF = operating_cash_flow - |capex|; a ticker with no capex tag at all should
        fall back to capex=0 (documented in _fcf_annual's merge fillna), not crash."""
        facts = pd.DataFrame(
            _facts_rows(
                "operating_cash_flow",
                [(date(2022, 12, 31), 40.0), (date(2023, 12, 31), 50.0)],
            )
        )
        result = _fcf_annual(facts, n_years=6)
        assert list(result["value"]) == [40.0, 50.0]

    def test_missing_cfo_field_returns_empty(self):
        facts = pd.DataFrame(_facts_rows("capex", [(date(2023, 12, 31), 5.0)]))
        result = _fcf_annual(facts, n_years=6)
        assert result.empty

    def test_both_fields_present_subtracts_absolute_capex(self):
        facts = pd.DataFrame(
            _facts_rows("operating_cash_flow", [(date(2023, 12, 31), 50.0)])
            + _facts_rows("capex", [(date(2023, 12, 31), -8.0)])
        )
        result = _fcf_annual(facts, n_years=6)
        assert list(result["value"]) == [42.0]  # 50 - |-8|

    def test_cagr_is_none_for_empty_fcf(self):
        facts = pd.DataFrame(_facts_rows("capex", [(date(2023, 12, 31), 5.0)]))
        result = _fcf_annual(facts, n_years=6)
        assert _cagr(result) is None
