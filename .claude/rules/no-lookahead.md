---
description: Point-in-time data integrity. All data, factor, backtest, discovery, and signal code.
paths: ["src/durable/data/**", "src/durable/factors/**", "src/durable/backtest/**", "src/durable/discovery/**", "src/durable/signals/**"]
---

# Rule: No look-ahead, ever

1. Any fundamental used at simulated date `T` must satisfy `available_at <= T`, where
   `available_at = SEC filing acceptance datetime + 1 trading day`.
2. Factor functions NEVER query the database directly. They receive a pre-filtered frame.
   All filtering happens in `store.as_of(T)` **and passes the firewall** (`data/firewall.py`).
3. Never use restated figures. Use the originally-filed value.
4. Never use `datetime.now()` or any wall-clock read inside `factors/` or `backtest/`.
5. Rebuild the universe for each date, including companies later delisted.
6. Any `.shift()`, `.rolling()`, `.resample()` — state the direction in a comment.
7. Lagged disclosures use the FILING date: 13F `filed_at` (45d), STOCK Act `filed_at` (45d),
   short interest `publication_date` (11+ business days).
8. **Never use adjusted-close-only price series.** Adjusted prices are retroactively restated
   on every split and dividend, so today's series differs from the one that existed at the
   historical date. Load raw OHLCV plus an explicit corporate-action table.
9. LLM-extracted features inherit `available_at` from the filing, not the extraction run, and
   must pass the contamination check against the model's training cutoff.
10. If you cannot determine `available_at` for a source, do not use that source. Ask.
