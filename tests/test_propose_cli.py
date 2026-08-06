"""Tests for the `propose` CLI's data-assembly layer (build_proposal). Hand-computed
fixtures against an in-memory PIT store. generate_proposal() itself already has full
coverage in tests/test_proposals.py; this file covers the glue this ticket adds:
loading holdings from tax_lots, pricing trades, and sizing buys/sells/trims."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from durable.data import store
from durable.execution.propose import ProposalDataUnavailable, build_proposal

AS_OF = date(2024, 6, 30)
CONFIG = {
    "portfolio": {
        "target_positions": 2,
        "buffer_rank": 80,
        "max_position_weight": 0.60,
        "max_sector_weight": 0.90,
        "max_turnover_annual": 0.60,
    },
    "reserve_cost_rate": 0.01,
}


@pytest.fixture
def conn():
    c = store.get_conn(":memory:")
    store.init_schema(c)
    yield c
    c.close()


def _seed_prices(conn, rows: list[dict]) -> None:
    df = pd.DataFrame(rows)
    df["open"] = df["close"]
    df["high"] = df["close"]
    df["low"] = df["close"]
    df["volume"] = 1_000_000
    df["available_at"] = pd.to_datetime(df["dt"])
    df = df[["ticker", "dt", "open", "high", "low", "close", "volume", "available_at"]]
    store.write_snapshot(conn, "bars_daily", df, snapshot_id="px1")


def _seed_lot(conn, **kw) -> None:
    defaults = {
        "sleeve": "C",
        "account": "taxable",
        "closed_at": None,
        "adjusted_basis": None,
        "wash_sale_deferred": 0,
        "holding_start": kw.get("acquired_at"),
        "proceeds": None,
        "realized_gain": None,
        "term": None,
    }
    defaults.update(kw)
    conn.execute(
        "INSERT INTO tax_lots (lot_id, ticker, sleeve, account, acquired_at, shares, "
        "cost_basis_per_share, adjusted_basis, wash_sale_deferred, holding_start, closed_at, "
        "proceeds, realized_gain, term) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            defaults["lot_id"],
            defaults["ticker"],
            defaults["sleeve"],
            defaults["account"],
            defaults["acquired_at"],
            defaults["shares"],
            defaults["cost_basis_per_share"],
            defaults["adjusted_basis"],
            defaults["wash_sale_deferred"],
            defaults["holding_start"],
            defaults["closed_at"],
            defaults["proceeds"],
            defaults["realized_gain"],
            defaults["term"],
        ],
    )


def _fake_scores() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "composite_score": 90,
                "rank": 1,
                "is_excluded": False,
                "implied_growth": 0.05,
                "sector": "Tech",
                "has_corporate_action": False,
            },
            {
                "ticker": "BBB",
                "composite_score": 80,
                "rank": 2,
                "is_excluded": False,
                "implied_growth": 0.05,
                "sector": "Tech",
                "has_corporate_action": False,
            },
        ]
    )


def test_no_scores_raises_data_unavailable(conn, monkeypatch):
    monkeypatch.setattr(
        "durable.portfolio.rank.score_universe",
        lambda conn, as_of, config: pd.DataFrame(),
        raising=False,
    )
    with pytest.raises(ProposalDataUnavailable, match="No scores"):
        build_proposal(conn, AS_OF, CONFIG)


def test_first_ever_buy_has_no_nav_but_flags_target_weight(conn, monkeypatch):
    """Empty portfolio (no tax lots yet): shares can't be sized without a known NAV, but the
    proposal must still name the target weight rather than silently proposing zero shares."""
    monkeypatch.setattr(
        "durable.portfolio.rank.score_universe",
        lambda conn, as_of, config: _fake_scores(),
        raising=False,
    )
    _seed_prices(
        conn,
        [
            {"ticker": "AAA", "dt": AS_OF, "close": 100.0},
            {"ticker": "BBB", "dt": AS_OF, "close": 50.0},
        ],
    )
    proposal = build_proposal(conn, AS_OF, CONFIG)

    buy_aaa = next(t for t in proposal.trades if t.ticker == "AAA")
    assert buy_aaa.action == "buy"
    assert buy_aaa.shares == 0.0
    assert "No current NAV" in buy_aaa.notes
    assert buy_aaa.limit_price == pytest.approx(100.0 * 1.01)  # reserve_cost_rate buffer


def test_sole_holding_over_concentration_cap_sells_every_open_lot(conn, monkeypatch):
    """CCC is the only holding, so its weight is 100% of NAV — S4 concentration always fires
    (hardcoded 12% threshold in _check_sell_rules) and, since weight > 12%, it's a full sell,
    not a trim. Every open lot for CCC must appear in the sell order — no partial selection
    needed, and nothing should be left out."""
    monkeypatch.setattr(
        "durable.portfolio.rank.score_universe",
        lambda conn, as_of, config: pd.concat(
            [
                _fake_scores(),
                pd.DataFrame(
                    [
                        {
                            "ticker": "CCC",
                            "composite_score": 10,
                            "rank": 3,
                            "is_excluded": False,
                            "implied_growth": 0.05,
                            "sector": "Health",
                            "has_corporate_action": False,
                        }
                    ]
                ),
            ],
            ignore_index=True,
        ),
        raising=False,
    )
    _seed_prices(
        conn,
        [
            {"ticker": "AAA", "dt": AS_OF, "close": 100.0},
            {"ticker": "BBB", "dt": AS_OF, "close": 50.0},
            {"ticker": "CCC", "dt": AS_OF, "close": 20.0},
        ],
    )
    _seed_lot(
        conn,
        lot_id="lot1",
        ticker="CCC",
        acquired_at=date(2022, 1, 1),
        shares=10.0,
        cost_basis_per_share=15.0,
    )
    _seed_lot(
        conn,
        lot_id="lot2",
        ticker="CCC",
        acquired_at=date(2022, 6, 1),
        shares=5.0,
        cost_basis_per_share=18.0,
    )

    proposal = build_proposal(conn, AS_OF, CONFIG)
    sell_ccc = next(t for t in proposal.trades if t.ticker == "CCC")

    assert sell_ccc.action == "sell"
    assert sell_ccc.shares == pytest.approx(15.0)  # 10 + 5, the full position
    assert set(sell_ccc.lot_ids) == {"lot1", "lot2"}
    assert sell_ccc.limit_price == pytest.approx(20.0 * 0.99)  # reserve_cost_rate buffer
