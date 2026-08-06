"""Tests for company scoring/ranking. TICKET-011. Hand-computed fixtures.

Durability-score components are hand-computed in the test docstrings/comments. Valuation is
verified by calling `factors.valuation.valuation_score` directly with the same hand-derived
raw inputs the fixture implies (ev, ebit, fcf, wacc, ...) and asserting `score_universe()`
reproduces exactly that value -- this avoids hand-solving the reverse-DCF Brent equation while
still pinning the orchestration to a value computed independently of `score_universe()` itself.
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import pytest

from durable.data.store import get_conn, init_schema, write_snapshot
from durable.factors.durability import durability_score
from durable.factors.valuation import valuation_score
from durable.portfolio.rank import SCORE_COLUMNS, score_universe

AS_OF = date(2024, 3, 1)

BASE_CONFIG = {
    "universe": {
        "min_market_cap": 0,
        "min_adv_60d": 0,
        "min_price": 0,
        "min_quarters_filed": 1,
    },
    "scoring": {
        "durability_max": 50,
        "valuation_max": 35,
        "momentum_max": 15,
        "overlay_gate_rank": 40,
    },
    "valuation": {
        "terminal_growth": 0.025,
        "equity_risk_premium": 0.05,
        "wacc_floor": 0.08,
        "max_implied_growth": 0.25,
        "max_ev_ebit": 45,
    },
}


@pytest.fixture
def conn():
    c = get_conn(":memory:")
    init_schema(c)
    return c


def _fact_rows(ticker: str, fields: dict[str, float], period_end: date, available_at: datetime):
    return [
        {
            "ticker": ticker,
            "field": field,
            "period_end": period_end,
            "value": value,
            "filed_at": available_at,
            "available_at": available_at,
            "accession": f"acc-{ticker}-{field}",
            "restated": False,
        }
        for field, value in fields.items()
    ]


def _write_ticker(
    conn,
    ticker: str,
    fields: dict[str, float],
    close: float,
    volume: float,
    insider_purchases: bool = False,
):
    period_end = date(2023, 12, 31)
    available_at = datetime(2024, 1, 15)
    facts = pd.DataFrame(_fact_rows(ticker, fields, period_end, available_at))
    write_snapshot(conn, "facts_fundamentals", facts, f"facts-{ticker}")

    bars = pd.DataFrame(
        [
            {
                "ticker": ticker,
                "dt": date(2024, 2, 28),
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": volume,
                "available_at": datetime(2024, 2, 28, 20, 0, 0),
            }
        ]
    )
    write_snapshot(conn, "bars_daily", bars, f"bars-{ticker}")

    if insider_purchases:
        form4 = pd.DataFrame(
            [
                {
                    "ticker": ticker,
                    "filer_name": f"CEO of {ticker}",
                    "filer_title": "CEO",
                    "txn_date": date(2024, 1, 10),
                    "txn_code": "P",
                    "shares": 1000.0,
                    "price": 100.0,
                    "shares_after": 10000.0,
                    "is_10b5_1": False,
                    "filed_at": datetime(2024, 1, 12),
                    "available_at": datetime(2024, 1, 12),
                    "accession": f"form4-{ticker}-1",
                },
                {
                    "ticker": ticker,
                    "filer_name": f"CFO of {ticker}",
                    "filer_title": "CFO",
                    "txn_date": date(2024, 1, 11),
                    "txn_code": "P",
                    "shares": 1000.0,
                    "price": 150.0,
                    "shares_after": 5000.0,
                    "is_10b5_1": False,
                    "filed_at": datetime(2024, 1, 13),
                    "available_at": datetime(2024, 1, 13),
                    "accession": f"form4-{ticker}-2",
                },
            ]
        )
        # Raw insider_txns schema only — no amount_usd/is_officer_director columns (those
        # are derived by rank.py::_prepare_form4_for_overlay from filer_title/shares/price
        # before insider_overlay() ever sees this data; see that function's docstring).
        write_snapshot(conn, "insider_txns", form4, f"form4-{ticker}")


def _build_store(conn, overlay_gate_rank: int) -> dict:
    """GOOD: valid valuation, strong insider buying. BAD: ebit <= 0 -> excluded. Both get the
    identical insider-buying pattern so the overlay-gating assertion is meaningful (BAD is
    outside the gate purely because of its rank, not because it lacks a signal).
    """
    good_fields = {
        "shares_outstanding": 1_000_000.0,
        "revenue": 500_000_000.0,
        "ebit": 50_000_000.0,
        "operating_cash_flow": 50_000_000.0,
        "capex": 10_000_000.0,
        "cash_and_equivalents": 20_000_000.0,
        "long_term_debt": 30_000_000.0,
    }
    bad_fields = {
        "shares_outstanding": 1_000_000.0,
        "revenue": 500_000_000.0,
        "ebit": -5_000_000.0,
        "operating_cash_flow": 10_000_000.0,
        "capex": 1_000_000.0,
        "cash_and_equivalents": 5_000_000.0,
        "long_term_debt": 5_000_000.0,
    }
    _write_ticker(conn, "GOOD", good_fields, close=100.0, volume=1_000_000, insider_purchases=True)
    _write_ticker(conn, "BAD", bad_fields, close=50.0, volume=500_000, insider_purchases=True)

    macro = pd.DataFrame(
        [
            {
                "series_id": "DGS10",
                "dt": date(2024, 1, 2),
                "value": 0.04,
                "available_at": datetime(2024, 1, 2),
            }
        ]
    )
    write_snapshot(conn, "macro_series", macro, "macro-dgs10")

    config = {
        **BASE_CONFIG,
        "scoring": {**BASE_CONFIG["scoring"], "overlay_gate_rank": overlay_gate_rank},
    }
    return config


class TestScoreUniverseColumns:
    def test_exact_column_contract(self, conn):
        """`score_universe()` must return exactly the 7 columns propose.py consumes."""
        config = _build_store(conn, overlay_gate_rank=40)
        result = score_universe(conn, AS_OF, config)
        assert list(result.columns) == SCORE_COLUMNS


class TestHandComputedDurability:
    """Hand-computed Piotroski + cash/safety subscore for GOOD (see module docstring math
    in the ticket writeup): cfo>0 is the only Piotroski signal satisfiable with a single
    fiscal period of data -> f_score=1 -> f_points=14/9. Net-debt/EBITDA = (30M-20M)/50M=0.2
    <=1.0 -> debt subscore=4.0 (max). No net_income/current-ratio/gross-margin data ->
    every other subscore is 0. roic_points=0 (needs >=5 EBIT periods). No red flags fire
    (every trigger needs data this fixture doesn't provide). Expected durability score:
    14/9 + 4.0 = 5.5555...
    """

    def test_good_durability_score_matches_hand_calc(self, conn):
        config = _build_store(conn, overlay_gate_rank=40)
        good_facts = pd.DataFrame(
            _fact_rows(
                "GOOD",
                {
                    "shares_outstanding": 1_000_000.0,
                    "revenue": 500_000_000.0,
                    "ebit": 50_000_000.0,
                    "operating_cash_flow": 50_000_000.0,
                    "capex": 10_000_000.0,
                    "cash_and_equivalents": 20_000_000.0,
                    "long_term_debt": 30_000_000.0,
                },
                date(2023, 12, 31),
                datetime(2024, 1, 15),
            )
        )
        expected_dur, _bd = durability_score(good_facts, is_financial=False)
        assert expected_dur == pytest.approx(14.0 / 9.0 + 4.0)

        result = score_universe(conn, AS_OF, config)
        good_row = result[result["ticker"] == "GOOD"].iloc[0]
        # composite = durability + valuation + momentum(0, insufficient bars) + overlay
        ev = 100_000_000.0 + 30_000_000.0 - 20_000_000.0

        # Sector = SIC code, which is currently always "UNKNOWN" (documented limitation —
        # see rank.py's module docstring). That means GOOD and BAD share ONE sector peer
        # group, and valuation_score()'s fcf-yield/ev-ebit points switch to peer-percentile
        # mode once a peer list has more than one value (factors/valuation.py::
        # ev_ebit_score/fcf_yield_score). BAD's own ev=50,000,000-5,000,000+5,000,000... =
        # market_cap(50M)+long_term_debt(5M)-cash(5M)=50M, fcf=operating_cash_flow(10M)-
        # capex(1M)=9M -> fcf_yield=9M/50M=0.18. BAD's ebit is negative so it has no
        # ev_ebit_ratio (excluded from that peer list, but NOT from the fcf-yield one,
        # which doesn't depend on ebit). To hand-verify score_universe()'s real, intended
        # sector-relative behavior, this must be passed the same peer context it builds.
        bad_fcf_yield = 9_000_000.0 / 50_000_000.0
        good_fcf_yield = 40_000_000.0 / ev
        expected_val, val_bd = valuation_score(
            ev=ev,
            ebit=50_000_000.0,
            fcf=40_000_000.0,
            fcf_5y_cagr=0.0,
            market_cap=100_000_000.0,
            dividend_yield=0.0,
            buyback_yield=0.0,
            debt_paydown_yield=0.0,
            risk_free_rate=0.04,
            fcf_5y_median=40_000_000.0,
            sector_ev_ebits=[ev / 50_000_000.0],  # GOOD only; BAD excluded (ebit <= 0)
            sector_fcf_yields=[good_fcf_yield, bad_fcf_yield],
            sector_gaps=[],  # both tickers' reverse_dcf_gap is None (fcf_5y_cagr=0.0)
        )
        assert expected_val is not None  # ev/ebit=2.2, well under the 45x hard floor
        expected_overlay = 3  # 2 officers/directors bought >= $250k aggregate, no 10b5-1
        expected_composite = expected_dur + expected_val + 0.0 + expected_overlay
        assert good_row["composite_score"] == pytest.approx(min(expected_composite, 100))
        assert good_row["implied_growth"] == val_bd.get("implied_growth")
        assert bool(good_row["is_excluded"]) is False


class TestExclusion:
    def test_negative_ebit_excludes_from_valuation(self, conn):
        """SPEC §3.2 hard floor: EBIT <= 0 -> valuation excluded -> is_excluded True."""
        config = _build_store(conn, overlay_gate_rank=40)
        result = score_universe(conn, AS_OF, config)
        bad_row = result[result["ticker"] == "BAD"].iloc[0]
        assert bool(bad_row["is_excluded"]) is True
        assert bad_row["implied_growth"] is None

    def test_good_ranks_above_bad(self, conn):
        config = _build_store(conn, overlay_gate_rank=40)
        result = score_universe(conn, AS_OF, config)
        good_rank = int(result.loc[result["ticker"] == "GOOD", "rank"].iloc[0])
        bad_rank = int(result.loc[result["ticker"] == "BAD", "rank"].iloc[0])
        assert good_rank == 1
        assert bad_rank == 2


class TestOverlayGating:
    """CLAUDE.md rule 6: overlays are tie-breakers, capped and gated to top-N base rank.
    GOOD and BAD get the IDENTICAL insider-buying pattern; only GOOD's base rank (1) is
    inside a gate of 1, so only GOOD's composite score should reflect the +3 insider
    overlay -- proving the gate acts on rank, not on the presence of a signal.
    """

    def test_only_top_ranked_name_gets_overlay(self, conn):
        config_gated = _build_store(conn, overlay_gate_rank=1)
        gated = score_universe(conn, AS_OF, config_gated)

        config_ungated = {
            **config_gated,
            "scoring": {**config_gated["scoring"], "overlay_gate_rank": 40},
        }
        ungated = score_universe(conn, AS_OF, config_ungated)

        # BAD is excluded either way (ebit <= 0), but its *base* composite is unaffected by
        # the overlay gate change since BAD's base rank (2) never qualifies at gate=1, and at
        # gate=40 BAD is still excluded from being a *buy* candidate -- only the raw
        # composite score number can move. It should NOT move: BAD's insider overlay would
        # only ever apply if BAD's base rank were <= the gate, and BAD is rank 2 > gate=1 in
        # the gated run. Confirm BAD's score is identical in both runs (never got an overlay
        # in either case because with only 2 names, gate=40 makes BAD rank-2-of-2 <= 40, so
        # BAD DOES get an overlay once gate=40; this asserts the gate=1 run denies it).
        bad_gated = gated.loc[gated["ticker"] == "BAD", "composite_score"].iloc[0]
        bad_ungated = ungated.loc[ungated["ticker"] == "BAD", "composite_score"].iloc[0]
        assert bad_ungated - bad_gated == pytest.approx(3.0)

        good_gated = gated.loc[gated["ticker"] == "GOOD", "composite_score"].iloc[0]
        good_ungated = ungated.loc[ungated["ticker"] == "GOOD", "composite_score"].iloc[0]
        # GOOD is base rank 1 in both cases -> gets the overlay either way.
        assert good_gated == pytest.approx(good_ungated)


class TestEmptyStore:
    def test_empty_store_returns_empty_frame_with_contract_columns(self, conn):
        """No data at all -> empty DataFrame with the exact 7-column contract, no exception."""
        result = score_universe(conn, AS_OF, BASE_CONFIG)
        assert result.empty
        assert list(result.columns) == SCORE_COLUMNS
