# Using the GUI

If you'd rather click buttons than type commands, this program has a browser-based GUI that
does everything the command line does. It runs on your own computer — nothing is uploaded
anywhere.

## Launch it

```bash
cd durable-alpha
make setup          # first time only — installs everything, including the GUI
make gui
```

Your browser should open automatically to `http://localhost:8501`. If it doesn't, open that
address yourself. To stop it, go back to the terminal and press `Ctrl+C`.

## How it's laid out

The left sidebar has two menus:

- **Section** — a broad category (Get Started, Data, Research & Backtesting, Discovery,
  Trading, Reports/Tax/Journal)
- **Step** — the specific action within that section

Steps are numbered 1 through 20 in the order most people actually use them — start at
**1. Welcome & Workflow Guide** and follow the table there if you're not sure where to begin.
You don't have to do every step, and nothing is lost by skipping around.

Every page follows the same pattern:

1. A plain-language explanation of what the step does and why it matters.
2. Any inputs it needs (a date, a ticker, a factor name — whatever the underlying command
   takes).
3. A button that runs it.
4. A live output box showing exactly what the command line would have printed, plus the exact
   command it ran (shown in small text above the output) — so you can learn the command-line
   equivalents as you go.

## Why it's safe to click around

- **The GUI never re-implements any logic.** Every button runs the identical `make <target>`
  command you'd type yourself. If a feature isn't finished on the command line yet, it isn't
  finished in the GUI either — you'll just see no output, which is expected, not a bug.
- **Nothing places a real trade except one page**: *Review & Submit Trades*. That page is
  deliberately hard to trigger by accident — it lists the exact proposal file, requires you to
  check a box confirming you've read it, and requires you to type the phrase `I APPROVE` before
  the submit button even becomes clickable. An AI assistant working in this repo is separately
  blocked from ever running this step (see `.claude/hooks/guard_bash.sh`).
- **Your API keys are never shown.** The Setup page tells you which keys are present or missing
  by name only — it never reads or displays their values.
- **Live trading stays off** until you deliberately edit `config/config.yaml` yourself and set
  `live_trading_approved: true`. Nothing in the GUI can flip that flag for you.

## If something looks stuck

Long steps (like updating market data, or a full backtest) can take a while — the output box
updates live as the command runs, so if you see new lines appearing every few seconds, it's
still working. If a command finishes with a nonzero exit code, the page will show a red error
banner; the log above it usually explains why (missing API key, missing data, etc.).
