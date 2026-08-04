---
description: Code conventions.
paths: ["src/**", "tests/**"]
---

# Rule: Python style

- Python 3.12. Type hints on public functions. `from __future__ import annotations`.
- Explicit readable pandas over clever one-liners. Re-read in three years.
- Factor docstrings state: data source, `available_at` logic, spec section.
- No module-level side effects, config reads, or API keys.
- Explicit documented column names. No positional column access.
- `Decimal` for money at execution and tax boundaries; `float` fine in research code.
- Raise on missing data. Never silently `fillna(0)` a financial metric.
- Tests use hand-computed fixtures, not golden files from the code under test.
- `ruff format` and `ruff check --fix` run automatically via the PostToolUse hook.
