"""Point-in-time DuckDB store. TICKET-001.

The single most important function is `as_of`: every read path goes through it, so look-ahead
is STRUCTURALLY impossible rather than merely discouraged. `firewall.py` is the independent
second check that catches paths bypassing this module.

def get_conn(path) -> duckdb connection.
def init_schema(conn) -> None. Idempotent. Includes the (ticker, available_at) index.
def write_snapshot(conn, table, df, snapshot_id) -> None. Append-only; raises on duplicate id.
    Snapshots are immutable -- the audit trail that makes `make reproduce` possible.
def as_of(conn, table, ts, tickers=None) -> DataFrame. Appends WHERE available_at <= ts.
    THE LOOK-AHEAD GUARD. Never bypass with raw SQL. Ends with assert_no_future().
"""

from __future__ import annotations
