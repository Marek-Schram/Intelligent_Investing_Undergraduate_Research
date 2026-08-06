"""Ingestion CLI orchestrator. Wires data/* loaders; every loader ends with a firewall call.

Data source: delegates entirely to prices.py (Alpaca, raw OHLCV), sec.py (SEC EDGAR XBRL
    facts), macro.py (FRED + Ken French Data Library), and universe.py (derived from stored
    fundamentals/prices). This module does no fetching of its own.
available_at logic: computed by the underlying ingestion functions this module calls. This
    orchestrator does not read or write `available_at` itself.
Spec section: docs/02 Data Sources.

Ticket note -- placeholder ticker universe: there is no config-driven ticker-list
infrastructure yet (that is a separate, un-built ticket). Until one exists, `--all` ingests a
small hardcoded seed list of large-cap US tickers below (SEED_TICKERS) -- a convenience for a
research/dev environment, NOT the production universe. A real run must point ingestion at a
genuine point-in-time universe source (e.g. historical index constituents, so delisted names
are never silently dropped -- see universe.py's docstring invariant that the 2008 universe
must still contain LEH/WM/BSC). Use `--tickers` to override this list for ad hoc runs.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import load_dotenv

from durable.config import PROJECT_ROOT, ConfigError, load_config
from durable.data import macro, prices, sec, universe
from durable.data.store import get_conn, init_schema

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    import duckdb

# Placeholder large-cap seed universe for research/dev environments only -- see module
# docstring. Real usage should replace this with a genuine point-in-time universe source.
SEED_TICKERS: tuple[str, ...] = (
    "AAPL",
    "MSFT",
    "AMZN",
    "GOOGL",
    "META",
    "JNJ",
    "PG",
    "JPM",
    "XOM",
    "V",
)

DEFAULT_PRICE_HISTORY_YEARS = 5


class MissingCredentialError(Exception):
    """Raised when a required API credential is missing from the environment."""


@dataclass(frozen=True)
class StepResult:
    """Outcome of one ingestion step, for the CLI report and the JSON audit trail."""

    name: str
    ok: bool
    detail: str


def _require_env(env: Mapping[str, str], var_name: str, feature: str) -> str:
    """Return `env[var_name]` or raise MissingCredentialError naming the missing key and
    the feature it gates, so the CLI can print an actionable message instead of a raw
    KeyError or a network exception several layers down."""
    value = env.get(var_name)
    if not value:
        raise MissingCredentialError(
            f"{var_name} is not set -- required for {feature}. "
            f"Copy .env.example to .env and fill in {var_name}, then re-run."
        )
    return value


def _ingest_prices(
    conn: duckdb.DuckDBPyConnection,
    tickers: Sequence[str],
    env: Mapping[str, str],
    start: date,
) -> list[StepResult]:
    feature = "price ingestion (Alpaca Markets IEX, raw OHLCV)"
    try:
        key = _require_env(env, "ALPACA_PAPER_KEY_ID", feature)
        secret = _require_env(env, "ALPACA_PAPER_SECRET_KEY", feature)
    except MissingCredentialError as exc:
        return [StepResult("prices", False, str(exc))]

    client = prices.get_price_client(key, secret)
    results: list[StepResult] = []
    for ticker in tickers:
        try:
            snapshot_id = prices.ingest_daily_bars(conn, client, ticker, start)
            results.append(StepResult(f"prices:{ticker}", True, f"snapshot={snapshot_id}"))
        except Exception as exc:  # noqa: BLE001 - report, never crash the whole run
            results.append(StepResult(f"prices:{ticker}", False, f"{type(exc).__name__}: {exc}"))
    return results


def _ingest_fundamentals(
    conn: duckdb.DuckDBPyConnection,
    tickers: Sequence[str],
    env: Mapping[str, str],
) -> list[StepResult]:
    feature = "fundamentals ingestion (SEC EDGAR XBRL facts)"
    try:
        identity = _require_env(env, "EDGAR_IDENTITY", feature)
    except MissingCredentialError as exc:
        return [StepResult("fundamentals", False, str(exc))]

    results: list[StepResult] = []
    for ticker in tickers:
        try:
            snapshot_id = sec.ingest_fundamentals(conn, ticker, identity)
            results.append(StepResult(f"fundamentals:{ticker}", True, f"snapshot={snapshot_id}"))
        except Exception as exc:  # noqa: BLE001
            results.append(
                StepResult(f"fundamentals:{ticker}", False, f"{type(exc).__name__}: {exc}")
            )
    return results


def _ingest_macro(conn: duckdb.DuckDBPyConnection, env: Mapping[str, str]) -> list[StepResult]:
    feature = "macro series ingestion (FRED)"
    try:
        api_key = _require_env(env, "FRED_API_KEY", feature)
    except MissingCredentialError as exc:
        return [StepResult("macro", False, str(exc))]

    try:
        snapshot_id = macro.ingest_macro(conn, api_key)
        return [StepResult("macro", True, f"snapshot={snapshot_id}")]
    except Exception as exc:  # noqa: BLE001
        return [StepResult("macro", False, f"{type(exc).__name__}: {exc}")]


FACTOR_FETCH_TIMEOUT_SECONDS = 30


def _ingest_factors(conn: duckdb.DuckDBPyConnection) -> list[StepResult]:
    """Ken French factor library needs no API key -- only network access, and unlike the
    Alpaca/EDGAR/FRED steps above there is no credential check to fail fast on when that
    network access isn't there. `pandas_datareader` has no built-in timeout, so without one
    a sandboxed/offline environment hangs here indefinitely instead of reporting a clean
    failure like every other step. A bounded socket timeout, scoped to just this call,
    turns "hangs forever" into "fails after 30s with a clear reason."
    """
    import socket

    previous_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(FACTOR_FETCH_TIMEOUT_SECONDS)
    try:
        snapshot_id = macro.ingest_factors(conn)
        return [StepResult("factors", True, f"snapshot={snapshot_id}")]
    except Exception as exc:  # noqa: BLE001
        return [
            StepResult(
                "factors",
                False,
                f"{type(exc).__name__}: {exc} (timed out after "
                f"{FACTOR_FETCH_TIMEOUT_SECONDS}s or failed -- no network access to Ken "
                "French's Data Library, most likely)",
            )
        ]
    finally:
        socket.setdefaulttimeout(previous_timeout)


def _build_universe(conn: duckdb.DuckDBPyConnection, as_of_date: date) -> list[StepResult]:
    """Report-only: build_universe() reads what was just ingested; nothing is written back
    (there is no universe table in the store -- it is recomputed per as_of date on read)."""
    try:
        universe_df, exclusions = universe.build_universe(conn, as_of_date)
        detail = (
            f"{len(universe_df)} tickers eligible, {len(exclusions)} exclusions "
            f"as of {as_of_date.isoformat()}"
        )
        return [StepResult("universe", True, detail)]
    except Exception as exc:  # noqa: BLE001
        return [StepResult("universe", False, f"{type(exc).__name__}: {exc}")]


def run_ingest(
    tickers: Sequence[str],
    conn: duckdb.DuckDBPyConnection,
    env: Mapping[str, str],
    *,
    price_history_start: date,
    universe_as_of: date,
) -> list[StepResult]:
    """Run every ingestion source for `tickers` against an already-initialized store.

    Each step is independent and failure-isolated: a missing credential or a vendor error
    in one step never prevents the others from running. Returns one StepResult per ticker
    per per-ticker source, plus one StepResult each for the macro, factors, and universe
    steps.
    """
    results: list[StepResult] = []
    results.extend(_ingest_prices(conn, tickers, env, price_history_start))
    results.extend(_ingest_fundamentals(conn, tickers, env))
    results.extend(_ingest_macro(conn, env))
    results.extend(_ingest_factors(conn))
    results.extend(_build_universe(conn, universe_as_of))
    return results


def format_report(results: Sequence[StepResult]) -> str:
    lines = ["Ingest report:"]
    for r in results:
        status = "OK  " if r.ok else "FAIL"
        lines.append(f"  [{status}] {r.name}: {r.detail}")
    n_ok = sum(1 for r in results if r.ok)
    n_fail = len(results) - n_ok
    lines.append(f"{n_ok} succeeded, {n_fail} failed out of {len(results)} step(s).")
    return "\n".join(lines)


def write_report_json(results: Sequence[StepResult], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"ingest_{timestamp}.json"
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "steps": [asdict(r) for r in results],
        "n_ok": sum(1 for r in results if r.ok),
        "n_failed": sum(1 for r in results if not r.ok),
    }
    out_path.write_text(json.dumps(payload, indent=2))
    return out_path


def _resolve_db_path(db_path_arg: str | None) -> Path:
    """--db-path wins outright (mainly for tests/ops); otherwise read config/config.yaml."""
    if db_path_arg:
        return Path(db_path_arg)
    config = load_config()
    db_path_cfg = config.get("data", {}).get("duckdb_path", "data/durable.duckdb")
    db_path = Path(db_path_cfg)
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    return db_path


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Ingest raw prices, fundamentals, macro, and factor data into the PIT "
        "DuckDB store."
    )
    parser.add_argument(
        "--all", action="store_true", help="Ingest every source for the seed ticker universe"
    )
    parser.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="Comma-separated tickers, overriding the seed list (e.g. AAPL,MSFT)",
    )
    parser.add_argument(
        "--as-of",
        type=str,
        default=None,
        help="ISO date for the universe-build step (default: today)",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Override the DuckDB path (default: config/config.yaml data.duckdb_path)",
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default=None,
        help="Override the report output directory (default: data/processed/ingest)",
    )
    args = parser.parse_args(argv)

    if not args.all and not args.tickers:
        parser.error("Specify --all to ingest the seed universe, or --tickers TICK1,TICK2,...")

    tickers = (
        tuple(t.strip().upper() for t in args.tickers.split(",") if t.strip())
        if args.tickers
        else SEED_TICKERS
    )
    universe_as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()

    try:
        db_path = _resolve_db_path(args.db_path)
    except ConfigError as exc:
        print(f"Configuration error: {exc}")
        return 1

    conn = get_conn(db_path)
    init_schema(conn)

    price_history_start = date.today() - timedelta(days=365 * DEFAULT_PRICE_HISTORY_YEARS)

    results = run_ingest(
        tickers,
        conn,
        os.environ,
        price_history_start=price_history_start,
        universe_as_of=universe_as_of,
    )

    print(format_report(results))

    out_dir = (
        Path(args.out_dir) if args.out_dir else PROJECT_ROOT / "data" / "processed" / "ingest"
    )
    report_path = write_report_json(results, out_dir)
    print(f"Report written to {report_path}")

    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
