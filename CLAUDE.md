# CLAUDE.md — Durable Alpha

Always-on context. Keep under ~200 lines; depth lives in `docs/` (read on demand) and
`.claude/rules/` (path-scoped). **Hard limits are enforced by `.claude/hooks/` — deterministic,
not advisory.**

## What this is

A rules-based, long-horizon equity system **and a research study** for one retail investor
(age 19, US taxable + Roth). Ranks companies on **durability** and **valuation**, holds 15–25
names for years, rebalances quarterly, measures itself honestly. **Not** a day-trading bot, not
an ML price predictor, not a leverage machine.

| Sleeve | % total | What | By |
|---|---|---|---|
| A Core index | 70% | Global index ETFs | Manual |
| B Factor tilt | 15% | Value/quality/momentum ETFs | Manual |
| C Durability | 8% | 15–25 stocks from the score | **This repo** |
| E Discovery | 2% | ≤8 under-followed small caps, staged | **This repo** |
| D Ballast | 5% | T-bills / short bonds | Manual |

## Non-negotiable

1. **Paper only until `config/config.yaml: live_trading_approved: true`.** Human-only flag;
   a hook blocks Claude from editing it.
2. **No look-ahead.** `available_at <= T`, from SEC filing acceptance. Lagged disclosures use
   FILING dates: 13F (45d), STOCK Act (45d), short interest (11+ business days).
3. **No leverage, shorting, options, margin, crypto.**
4. **Every order is human-reviewed.** System writes a proposal; a separate command submits.
5. **Min holding 12 months** unless a written sell rule fires.
6. **Overlays are tie-breakers**, capped and gated to top-40.
7. **Reporting, research, and tax are read-only and may be automated. Execution may not.**
8. **Sleeve E ≤ 2% total, 8 positions, 0.25% each**, never raised on good performance.
9. **LLM output needs a filing citation to score.** Extraction, never prediction.
10. **Preregister before testing.** Log every run.

## Layout

```
src/durable/
  data/       PIT DuckDB store · firewall (leakage assertions) · ingestion
  factors/    durability · valuation · momentum · overlays · ic (factor validation)
  portfolio/  ranking -> weights -> proposals
  backtest/   walk-forward · cpcv (PBO) · costs (Almgren-Chriss) · stats
  discovery/  Sleeve E: screens · manipulation · tranches · dossiers
  signals/    LLM extraction · 13F · distress · short interest · credit
  tax/        lots · harvesting · wash sales · after-tax
  execution/  Alpaca adapter (guarded)
  reporting/  performance · attribution · narrative · research export
  research/   decision journal · calibration · literature · preregistration
docs/         00 spec · 01 arch · 02 data · 03 protocol · 04 risk · 05 roadmap · 06 playbook
              07 reporting · 08 discovery · 09 validation · 10 signals · 11 tax
              12 research · 13 open-source audit · 14 simulation findings
```

## Commands

```bash
make lint / test / ingest / score AS_OF=
make backtest SEGMENT=      # walk-forward
make cpcv                   # combinatorial purged CV -> PBO
make ic FACTOR=             # information coefficient + decay (factor validation)
make leakage-audit          # firewall + contamination checks
make discover / dossier TICKER=
make extract TICKER=        # LLM filing extraction
make propose AS_OF= / submit
make report TYPE= / research-export
make tax-review / journal / reproduce COMMIT=
```

## Conventions

- Python 3.12, `uv`, `ruff`, `pytest`, type hints everywhere.
- DuckDB over Parquet; never overwrite a snapshot, write a new dated partition.
- `Decimal` for money at execution and tax boundaries; `float` fine in research code.
- Secrets only from `.env`. A hook blocks reads/writes of `.env`.
- Broker functions live in `execution/` and take `dry_run: bool = True`.
- `reporting/`, `research/`, `tax/` must never import `execution/`. Tests assert it.
- **Never use adjusted-close-only price loaders.** The firewall rejects them — adjusted series
  are retroactively restated and silently leak future corporate actions.

## How to work here

- Take the lowest unfinished ticket in `specs/BUILD_TICKETS.md`. Implement, test, stop.
- Read the doc the ticket names **before** writing code.
- Prefer boring readable pandas. This gets re-read in three years to explain a trade.
- Missing data or ambiguous spec => **stop and ask.** Silent proxies are how backtests lie.
- One ticket per session. Fresh session per ticket.

## Done means

Test passes against a hand-computed fixture · docstring names data source, `available_at`
logic, and spec section · backtest still runs end to end. Not before.
