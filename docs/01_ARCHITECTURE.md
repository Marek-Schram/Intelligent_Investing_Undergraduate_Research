# 01 — Architecture

## Principles
1. **Deterministic and replayable.** Same as-of + same snapshot => byte-identical scores.
2. **Snapshot-first.** Raw data written once, immutably, dated partitions.
3. **Backtest and live share the same code.** If they diverge, the backtest is fiction.
4. **Execution is a thin guarded shell.**
5. **Read-only modules can be automated.** `reporting/`, `research/`, `tax/` never import
   `execution/` — tests and a PreToolUse hook both enforce it.
6. **Two independent leakage guards.** `store.as_of()` filters; `firewall.py` asserts. The
   second catches paths that bypass the first.

## Flow
```
SOURCES            INGEST              STORE                 GUARD
EDGAR ----------> data/sec ------> facts_fundamentals --> store.as_of()
prices ---------> data/prices ---> bars_daily (RAW) -----> firewall.assert_no_future()
FRED -----------> data/macro ----> macro_series           firewall.assert_raw_prices()
Form 4 ---------> data/insider --> insider_txns           firewall.assert_lagged_disclosure()
STOCK Act ------> data/political-> political_txns              |
13F ------------> data/institutional-> institutional_holdings  |
FINRA SI -------> data/short ----> short_interest              |
TRACE ----------> data/credit ---> credit_spreads              |
filings (LLM) --> signals/extract-> filing_extractions         v
                                              +----------------------------+
                                              | universe · factors · ic    |
                                              | signals · portfolio.rank   |
                                              +------+---------------+-----+
                                                     |               |
                                    backtest.walk_fwd|      tax.select_lots
                                    backtest.cpcv -> PBO   tax.wash_sale_check
                                                     |               |
                                    reporting.* research.*   execution.propose()
                                    (safe to automate)              | HUMAN
                                                            execution.submit()
```

## Modules
| Package | Responsibility |
|---|---|
| `data/` | store (PIT) · **firewall (independent leakage assertions)** · sec · prices · macro · insider · political · institutional · short_interest · credit · coverage · universe |
| `factors/` | durability · valuation · momentum · overlays · **ic (factor validation)** |
| `signals/` | extract (LLM) · institutional · distress (Merton DD) · **contamination (alpha decay)** |
| `discovery/` | Sleeve E: universe · manipulation · neglect · screens · score · tranche · dossier |
| `backtest/` | engine (walk-forward) · **cpcv (PBO)** · costs · **impact (Almgren-Chriss)** · stats · attribution |
| `tax/` | lots · selection · harvest · wash_sale · after_tax |
| `reporting/` | performance · attribution · narrative · research_export · report · memo |
| `research/` | journal · calibration · literature · preregister |
| `execution/` | broker · propose · **sequencer** · submit · reconcile — all `dry_run: bool = True` |

### Execution sequencing (added v1.3 — non-negotiable)
Orders are **never** emitted as one undifferentiated batch. The sequencer enforces:

1. **Sells execute first**, and their proceeds are recorded **net of cost**.
2. **Buys are sized from cash actually on hand**, with transaction costs reserved:
   `affordable = cash / (1 + cost_rate)`.
3. If desired buys exceed affordable cash, **all buys scale down pro-rata** and the shortfall is
   logged. The system never assumes unsettled proceeds are spendable.

**Why this is architectural rather than a parameter.** The naive approach — compute
`target = NAV × weight` and execute everything against it — silently produces negative cash,
because transaction costs are paid from cash but never budgeted into the target. In simulation
this occurred in **11 of 54 quarters**. A real broker rejects those orders or charges margin
interest; either way the backtest is measuring a portfolio the account could not have held.

Critically, **increasing a cash buffer does not fix it** — tested at 0.5/1.0/1.5/2.0%, negative
quarters went 4→4→7→8, i.e. worse. Sequencing eliminates it entirely (11 → **0**) at a cost of
0.06pp/yr in CAGR.

## Schema additions
```sql
CREATE TABLE institutional_holdings (manager_cik INT, manager_name VARCHAR, ticker VARCHAR,
  cusip VARCHAR, shares DOUBLE, value DOUBLE, period_end DATE, filed_at TIMESTAMP,
  available_at TIMESTAMP, pct_of_portfolio DOUBLE, change_type VARCHAR, snapshot_id VARCHAR);
CREATE TABLE short_interest (ticker VARCHAR, settlement_date DATE, publication_date DATE,
  available_at TIMESTAMP, shares_short BIGINT, pct_float DOUBLE, days_to_cover DOUBLE);
CREATE TABLE credit_spreads (ticker VARCHAR, cusip VARCHAR, dt DATE, yield DOUBLE,
  benchmark_yield DOUBLE, spread_bps DOUBLE, available_at TIMESTAMP);
CREATE TABLE filing_extractions (accession VARCHAR, ticker VARCHAR, field VARCHAR,
  value VARCHAR, citation VARCHAR, confidence DOUBLE, prompt_version VARCHAR,
  model_version VARCHAR, extracted_at TIMESTAMP, available_at TIMESTAMP,
  PRIMARY KEY (accession, field, prompt_version, model_version));
CREATE TABLE factor_ic (as_of DATE, factor VARCHAR, horizon_q INT, ic DOUBLE,
  n_names INT, snapshot_id VARCHAR);
CREATE TABLE firewall_violations (detected_at TIMESTAMP, table_name VARCHAR, as_of DATE,
  n_rows INT, detail VARCHAR);
CREATE TABLE tax_lots (lot_id VARCHAR PRIMARY KEY, ticker VARCHAR, sleeve VARCHAR,
  account VARCHAR, acquired_at DATE, shares DOUBLE, cost_basis_per_share DECIMAL(18,6),
  adjusted_basis DECIMAL(18,6), wash_sale_deferred DECIMAL(18,6), holding_start DATE,
  closed_at DATE, proceeds DECIMAL(18,6), realized_gain DECIMAL(18,6), term VARCHAR);
```
Index on `(ticker, available_at)` — what makes 25-year PIT backtests fast enough on a laptop.

## Runtime
Local dev (you, in Claude Code) · nightly ingestion + data-quality + **firewall audit** (cron) ·
weekly performance pulse (scheduled, read-only) · quarterly score/propose/memo/report (manual
kickoff, reviewed) · **never automated: order submission**.

## Non-goals
No intraday or tick data. No neural nets or GBM return prediction — ~112 quarterly observations
against thousands of candidate features. **No automated factor mining** (docs/13 §3). Use LLMs
for *text*, not price. One repo, one DuckDB file, cron.
