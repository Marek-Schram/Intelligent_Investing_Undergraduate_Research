"""Durable Alpha GUI — a browser front end for every `make` command in this project.

Launch with `make gui` (or `streamlit run src/durable/gui/app.py`).

Design rule: this file never re-implements logic. Every action button runs the exact
same `make <target>` (see runner.run_make) that you'd type at a terminal — the GUI is a
front door, not a rewrite. Every command behind every button has a real implementation;
a command that prints nothing means there's no data to act on yet (run Setup and Update
Market Data first), not that the feature is unbuilt.
"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from durable.gui.runner import (
    OUTPUT_DIRS,
    PROJECT_ROOT,
    list_output_files,
    list_recent_files,
    run_make,
    run_streaming,
)

st.set_page_config(page_title="Durable Alpha", page_icon="📈", layout="wide")

ENV_FILE = PROJECT_ROOT / ".env"
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"
CONFIG_FILE = PROJECT_ROOT / "config" / "config.yaml"
CONFIG_EXAMPLE = PROJECT_ROOT / "config" / "config.example.yaml"

FACTOR_CHOICES = ["durability", "valuation", "momentum", "overlays"]
REPORT_TYPES = ["pulse", "quarterly", "research", "event", "annual"]
SEGMENT_CHOICES = ["design", "validation", "holdout"]


# --------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------


def _new_output_files_since(start_ts: float) -> list[Path]:
    """Every file under proposals/, reports/, research/, or data/processed/ whose mtime is at
    or after `start_ts` — i.e. what a command just wrote, regardless of which folder it used."""
    found: list[Path] = []
    for directory in OUTPUT_DIRS.values():
        if directory.is_dir():
            found.extend(
                p for p in directory.rglob("*") if p.is_file() and not p.name.startswith(".")
            )
    recent = {p for p in found if p.stat().st_mtime >= start_ts - 1}
    return sorted(recent, key=lambda p: p.stat().st_mtime, reverse=True)[:10]


def _render_run_aftermath(new_files: list[Path], code: int, output: str) -> None:
    """Show whatever a command actually produced: preview any new files inline, or say plainly
    that nothing was written if the command claimed success but left no trace."""
    if new_files:
        st.markdown(f"**This run wrote {len(new_files)} file(s) — previewed below:**")
        for p in new_files:
            with st.expander(f"📄 {p.relative_to(PROJECT_ROOT)}", expanded=len(new_files) == 1):
                render_file_preview(p)
    elif code == 0 and not output.strip():
        st.info(
            "This command exited successfully but printed nothing and wrote no new file into "
            "`proposals/`, `reports/`, `research/`, or `data/processed/`. That usually means "
            "there was nothing to do yet — most commands explain what's missing (data, config, "
            "a prior step) and exit non-zero instead of going silent, so this is the unusual case."
        )


def run_button(
    key: str,
    label: str,
    run_fn,
    *,
    help: str | None = None,
    primary: bool = True,
    watch_outputs: bool = True,
) -> None:
    """A button that runs `run_fn()` (which streams output), remembers the last result so it's
    still visible after you navigate to another page and back, and — when `watch_outputs` is
    set — previews any file the command wrote inline instead of making you go find it."""
    clicked = st.button(
        label, key=f"btn_{key}", type="primary" if primary else "secondary", help=help
    )
    if clicked:
        start_ts = time.time()
        code, output = run_fn()
        new_files = _new_output_files_since(start_ts) if watch_outputs else []
        st.session_state[f"result_{key}"] = (code, output, time.time(), new_files)
        _render_run_aftermath(new_files, code, output)
    elif f"result_{key}" in st.session_state:
        code, output, ts, new_files = st.session_state[f"result_{key}"]
        st.caption(
            f"Output from the last run, at {time.strftime('%H:%M:%S', time.localtime(ts))}."
        )
        st.code(output[-8000:] if output else "(no output)", language="text")
        (st.success if code == 0 else st.error)(
            "Finished successfully (exit code 0)." if code == 0 else f"Exited with code {code}."
        )
        _render_run_aftermath(new_files, code, output)


def as_of_input(key: str) -> str:
    picked = st.date_input("As-of date", value=date.today(), key=f"date_{key}")
    return picked.isoformat()


def env_status() -> dict[str, bool]:
    """True/False per key — never reads or displays the actual secret values."""
    keys = [
        "EDGAR_IDENTITY",
        "ALPACA_PAPER_KEY_ID",
        "ALPACA_PAPER_SECRET_KEY",
        "FRED_API_KEY",
    ]
    if not ENV_FILE.exists():
        return dict.fromkeys(keys, False)
    text = ENV_FILE.read_text()
    present: dict[str, bool] = {}
    for key in keys:
        for line in text.splitlines():
            if line.strip().startswith(f"{key}="):
                value = line.split("=", 1)[1].strip().strip('"')
                present[key] = bool(value)
                break
        else:
            present[key] = False
    return present


MAX_PREVIEW_BYTES = 5_000_000  # larger files still download, just skip the inline render


def render_file_preview(path: Path) -> None:
    """Render `path` inline (table for CSV, tree for JSON, text for markdown/logs, image for
    pictures) plus a download button. Used by the Files page and the Submit page's file picker
    so a proposal or report can always be read before you act on it, not just located."""
    if not path.is_file():
        st.warning(f"File not found: `{path}`")
        return

    size = path.stat().st_size
    modified = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(path.stat().st_mtime))
    st.caption(f"`{path.relative_to(PROJECT_ROOT)}` — {size:,} bytes — modified {modified}")

    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            df = pd.read_csv(path)
            st.dataframe(df, use_container_width=True)
            st.caption(f"{len(df):,} rows × {len(df.columns)} columns")
        elif suffix == ".json":
            st.json(json.loads(path.read_text()))
        elif suffix in (".md", ".markdown"):
            st.markdown(path.read_text())
        elif suffix in (".txt", ".log", ".yaml", ".yml"):
            st.code(path.read_text(), language="text")
        elif suffix in (".png", ".jpg", ".jpeg", ".gif"):
            st.image(str(path))
        elif suffix == ".pdf":
            st.info("PDF preview isn't supported inline here — use the download button below.")
        else:
            st.info(f"No inline preview for `{suffix or '(no extension)'}` files — download it.")
    except Exception as exc:
        st.error(f"Could not preview this file: {exc}")

    if size <= MAX_PREVIEW_BYTES:
        st.download_button(
            "⬇️ Download this file",
            data=path.read_bytes(),
            file_name=path.name,
            key=f"dl_{path}",
        )
    else:
        st.caption(
            f"File is {size:,} bytes, too large to offer as a download here — open it "
            f"directly at `{path}`."
        )


def step_header(number: int, total: int, title: str, blurb: str) -> None:
    st.header(f"{title}")
    st.caption(f"Step {number} of {total} in the suggested order")
    st.markdown(blurb)
    st.divider()


TOTAL_STEPS = 20


# --------------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------------


def page_welcome() -> None:
    st.title("📈 Durable Alpha")
    st.markdown(
        "This is a point-and-click front end for the same program you'd otherwise run from a "
        "terminal with `make <command>`. Every button on every page below runs that exact command "
        "and shows you its live output — nothing here works differently than the command line, "
        "it's just easier to find and fill in."
    )
    st.info(
        "**New here?** Use the **Section** and **Step** menus in the left sidebar. Steps are "
        "numbered in the order most people follow them, top to bottom. You don't have to do them "
        "all, and you can always come back — nothing here is destructive except the trading step, "
        "which is deliberately hard to trigger by accident."
    )

    st.subheader("The suggested order")
    st.markdown(
        """
| # | Step | What it does |
|---|---|---|
| 1 | Welcome & Workflow Guide | You are here |
| 2 | Setup Check & Install | Install dependencies, check API keys are in place |
| 3 | Run Tests | Confirm the program itself is working correctly on your machine |
| 4 | Update Market Data | Download prices, filings, and other raw data |
| 5 | Data Safety Check | Confirm the data has no "look-ahead" leaks |
| 6 | Dry-Run Simulation | A synthetic end-to-end rehearsal, no real data needed |
| 7 | Score Companies | Rank companies 0–100 on durability + valuation + momentum |
| 8 | Test a Factor (IC) | Check whether one ranking ingredient actually predicts returns |
| 9 | Backtest the Strategy | See how the rules would have performed historically |
| 10 | Validate Robustness (CPCV) | Estimate the odds the backtest is just overfit |
| 11 | Discover New Ideas | Screen for small, under-followed companies (Sleeve E) |
| 12 | Research One Stock | A full one-page dossier on a single ticker |
| 13 | Extract Filing Data | Pull citation-backed facts out of a company's SEC filing |
| 14 | Propose Trades | Generate a suggested rebalance — **sends nothing** |
| 15 | Review & Submit Trades | The only step that can place real orders — human-gated |
| 16 | Performance Report | Returns, risk, and benchmark comparison |
| 17 | Research Export | A full data/figures bundle for deeper analysis |
| 18 | Tax Review | Lots, harvest candidates, wash-sale check |
| 19 | Decision Journal | Score how calibrated your past predictions were |
| 20 | Reproduce a Past Report | Regenerate an old report byte-for-byte, to check reproducibility |
        """
    )
    st.subheader("A few things worth knowing before you start")
    st.markdown(
        """
- **Nothing trades by itself.** Steps 1–14 and 16–20 never touch a broker account. Only step 15
  can, and it requires you to type an explicit confirmation phrase first.
- **This project starts in paper trading.** Real money is only ever at risk if you've deliberately
  changed `config/config.yaml` yourself — the GUI can't do that for you.
- **Steps early in the order gate the ones after them.** Score Companies, Discover, Propose,
  Backtest, and most others need real ingested data first (Update Market Data) — if one refuses
  to run, it will tell you exactly what's missing and which earlier step provides it.
- **Every button shows the exact command it's running**, right above the output box, so you can
  learn the command-line equivalents as you go.
- **Anything a command writes to disk — a proposal, a report, a CSV — can be opened right here.**
  Use **📁 Files & Outputs** in the sidebar to browse and view it without leaving the browser.
        """
    )


def page_files() -> None:
    st.title("📁 Files & Outputs")
    st.markdown(
        "Every proposal, report, and research file this program writes lands in one of the "
        "folders below. Pick a folder, pick a file, and it opens right here — a CSV renders as "
        "a table, a report as text or a chart, and everything has a download button."
    )
    st.divider()

    folder_label = st.selectbox("Folder", list(OUTPUT_DIRS.keys()), key="files_folder")
    directory = OUTPUT_DIRS[folder_label]
    files = list_output_files(directory)

    if not files:
        st.info(
            f"No files in `{directory.relative_to(PROJECT_ROOT)}` yet. Run one of the "
            "commands elsewhere in this app that writes to this folder, then come back."
        )
        return

    rows = [
        {
            "File": str(p.relative_to(directory)),
            "Size (bytes)": p.stat().st_size,
            "Modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime)),
        }
        for p in files
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.divider()
    options = [str(p.relative_to(directory)) for p in files]
    chosen = st.selectbox("Open a file", options, key="files_chosen")
    st.subheader(chosen)
    render_file_preview(directory / chosen)


def page_setup() -> None:
    step_header(
        2,
        TOTAL_STEPS,
        "Setup Check & Install",
        "Make sure dependencies are installed and your API keys are in place. You only need to "
        "do this once (and again any time you add a new key).",
    )

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**`.env`** (your API keys)")
        if ENV_FILE.exists():
            st.success("`.env` exists.")
            statuses = env_status()
            for key, present in statuses.items():
                st.markdown(f"- {'✅' if present else '⬜'} `{key}`")
            if not all(statuses.values()):
                st.caption(
                    "Missing keys just mean the features that need them (SEC filings, paper "
                    "trading, macro data) won't work yet. Edit `.env` in a text editor to add "
                    "them — the GUI deliberately never displays or writes secret values for you."
                )
        else:
            st.warning("`.env` does not exist yet.")
            if st.button("Create .env from .env.example", key="btn_create_env"):
                ENV_FILE.write_text(ENV_EXAMPLE.read_text())
                st.success("Created `.env`. Now open it in a text editor and fill in your keys.")
                st.rerun()

    with col2:
        st.markdown("**`config/config.yaml`** (your strategy settings)")
        if CONFIG_FILE.exists():
            st.success("`config/config.yaml` exists.")
            st.caption(
                "Leave `live_trading_approved: false` until you have deliberately decided to go "
                "live. Nothing in this GUI can change that flag."
            )
        else:
            st.warning("`config/config.yaml` does not exist yet.")
            if st.button("Create config.yaml from config.example.yaml", key="btn_create_config"):
                CONFIG_FILE.write_text(CONFIG_EXAMPLE.read_text())
                st.success("Created `config/config.yaml` with safe defaults (paper trading only).")
                st.rerun()

    st.divider()
    st.markdown("**Install / update dependencies**")
    st.markdown("Runs `make setup`, which installs everything this program needs to run.")
    run_button("setup", "Install dependencies", lambda: run_make("setup"), watch_outputs=False)


def page_test() -> None:
    step_header(
        3,
        TOTAL_STEPS,
        "Run Tests (Health Check)",
        "This project ships with an automated test suite. Running it confirms the program works "
        "correctly on your computer before you trust it with anything else.",
    )
    st.markdown("**Test suite** — runs `make test`. Takes a minute or two.")
    run_button("test", "Run the test suite", lambda: run_make("test"), watch_outputs=False)
    st.divider()
    st.markdown("**Code style check** — runs `make lint`. Only useful if you're editing the code.")
    run_button(
        "lint", "Run the linter", lambda: run_make("lint"), primary=False, watch_outputs=False
    )


def page_ingest() -> None:
    step_header(
        4,
        TOTAL_STEPS,
        "Update Market Data (Ingest)",
        "Downloads prices, company filings, and other raw data into the local database "
        "(`data/durable.duckdb`). Run this before scoring, backtesting, or discovering — stale "
        "data gives stale answers. Requires the API keys from the Setup step.",
    )
    run_button("ingest", "Update all data", lambda: run_make("ingest"), watch_outputs=False)


def page_leakage_audit() -> None:
    step_header(
        5,
        TOTAL_STEPS,
        "Data Safety Check (Leakage Audit)",
        "Sweeps the database for 'look-ahead' problems: rows dated in the future, disclosures "
        "used before they were actually filed, or price series that have been silently adjusted "
        "for later corporate actions. This is what keeps a backtest honest.",
    )
    run_button(
        "leakage_audit",
        "Run the leakage audit",
        lambda: run_make("leakage-audit"),
        watch_outputs=False,
    )


def page_simulate() -> None:
    step_header(
        6,
        TOTAL_STEPS,
        "Dry-Run Simulation",
        "An end-to-end rehearsal on synthetic data — no real data or API keys required. Confirms "
        "the core accounting rules hold (no negative cash, the books always reconcile) before you "
        "trust the system with anything real.",
    )
    run_button("simulate", "Run the simulation", lambda: run_make("simulate"), watch_outputs=False)


def page_score() -> None:
    step_header(
        7,
        TOTAL_STEPS,
        "Score Companies",
        "Ranks companies 0–100 on durability, valuation, and momentum as of a given date. This is "
        "the core output the rest of the system builds on.",
    )
    as_of = as_of_input("score")
    run_button("score", "Score companies", lambda: run_make("score", {"AS_OF": as_of}))


def page_ic() -> None:
    step_header(
        8,
        TOTAL_STEPS,
        "Test a Factor (Information Coefficient)",
        "Checks whether one ingredient of the score (durability, valuation, momentum, or the "
        "insider/political/institutional overlays) actually predicts future returns on its own — "
        "separate from whether the whole portfolio looks good. This is what catches a factor that "
        "only *seems* to work because of how the portfolio was built around it.",
    )
    factor = st.selectbox("Factor", FACTOR_CHOICES, key="factor_ic")
    run_button("ic", "Test this factor", lambda: run_make("ic", {"FACTOR": factor}))


def page_backtest() -> None:
    step_header(
        9,
        TOTAL_STEPS,
        "Backtest the Strategy",
        "Runs the strategy's rules against historical data to see how they would have performed. "
        "`design` is the period the rules were built on, `validation` is held out to check them, "
        "and `holdout` is touched last of all, if ever.",
    )
    choice = st.selectbox("Segment", SEGMENT_CHOICES + ["Custom…"], key="segment_choice")
    if choice == "Custom…":
        segment = st.text_input("Custom segment (e.g. 2020-2024)", key="segment_custom")
    else:
        segment = choice
    run_button("backtest", "Run backtest", lambda: run_make("backtest", {"SEGMENT": segment}))


def page_cpcv() -> None:
    step_header(
        10,
        TOTAL_STEPS,
        "Validate Robustness (CPCV)",
        "Combinatorial Purged Cross-Validation: reruns the backtest across many purged, "
        "embargoed splits of history and estimates the **probability the strategy is simply "
        "overfit** to the one history we happened to have. A high probability here is a kill "
        "signal, no matter how good the plain backtest looked.",
    )
    run_button("cpcv", "Run CPCV validation", lambda: run_make("cpcv"))


def page_discover() -> None:
    step_header(
        11,
        TOTAL_STEPS,
        "Discover New Ideas (Sleeve E)",
        "Runs the small-cap discovery screens and produces a watchlist of under-followed "
        "companies worth a closer look. This step never places or proposes an order — it only "
        "surfaces candidates for you to research further with the Dossier step.",
    )
    as_of = as_of_input("discover")
    run_button("discover", "Run discovery screens", lambda: run_make("discover", {"AS_OF": as_of}))


def page_dossier() -> None:
    step_header(
        12,
        TOTAL_STEPS,
        "Research One Stock (Dossier)",
        "Builds a single-ticker research dossier: the score, the red-flag checks, and the case "
        "for and against. Use this to dig into any name from the score or discovery steps.",
    )
    ticker = st.text_input("Ticker", key="ticker_dossier", placeholder="AAPL").strip().upper()
    disabled = not ticker
    st.button(
        "Build dossier", key="btn_dossier_disabled_hint", disabled=True, help="pick a ticker first"
    ) if disabled else run_button(
        "dossier", "Build dossier", lambda: run_make("dossier", {"TICKER": ticker})
    )


def page_extract() -> None:
    step_header(
        13,
        TOTAL_STEPS,
        "Extract Filing Data (LLM)",
        "Pulls specific, citation-backed facts out of a company's SEC filings using an LLM. Every "
        "extracted claim must point to a specific place in the filing to count — this step never "
        "asks the model to predict anything, only to read.",
    )
    ticker = st.text_input("Ticker", key="ticker_extract", placeholder="AAPL").strip().upper()
    disabled = not ticker
    st.button(
        "Extract filing data",
        key="btn_extract_disabled_hint",
        disabled=True,
        help="pick a ticker first",
    ) if disabled else run_button(
        "extract", "Extract filing data", lambda: run_make("extract", {"TICKER": ticker})
    )


def page_propose() -> None:
    step_header(
        14,
        TOTAL_STEPS,
        "Propose Trades",
        "Generates a suggested rebalance — which names to buy, sell, or trim — based on the "
        "current scores and your existing holdings. **This step sends nothing to any broker.** "
        "It only writes a proposal for you to review in the next step.",
    )
    as_of = as_of_input("propose")
    run_button("propose", "Generate proposal", lambda: run_make("propose", {"AS_OF": as_of}))


def page_submit() -> None:
    step_header(
        15,
        TOTAL_STEPS,
        "Review & Submit Trades",
        "The only step in this whole program that can place a real order. It is deliberately "
        "hard to trigger by accident — a Claude Code hook blocks the AI assistant from ever "
        "running it, and this page requires you, a human, to read the proposal and type an "
        "explicit approval phrase before the button even becomes clickable.",
    )
    st.warning(
        "**Stop and read the proposal file before doing anything on this page.** It lists exactly "
        "what would be bought, sold, or trimmed, and why."
    )

    candidates = list_recent_files(PROJECT_ROOT / "proposals") + list_recent_files(
        PROJECT_ROOT / "reports", patterns=("*.json", "*.csv")
    )
    options = [str(p.relative_to(PROJECT_ROOT)) for p in candidates]
    if options:
        chosen = st.selectbox("Proposal file", options, key="submit_file_select")
        st.markdown("**Preview:**")
        render_file_preview(PROJECT_ROOT / chosen)
    else:
        st.info(
            "No proposal files found yet in `proposals/` or `reports/`. "
            "Run **Propose Trades** first."
        )
        chosen = st.text_input("Or type a proposal file path", key="submit_file_manual")
        if chosen:
            st.markdown("**Preview:**")
            render_file_preview(PROJECT_ROOT / chosen)

    st.divider()
    reviewed = st.checkbox(
        "I have opened and read this proposal file, and I understand every trade it lists.",
        key="submit_reviewed",
    )
    confirm_text = st.text_input(
        'Type exactly "I APPROVE" to unlock the submit button', key="submit_confirm_text"
    )
    ready = reviewed and confirm_text.strip() == "I APPROVE" and bool(chosen)

    if not ready:
        st.button("Submit these trades", disabled=True, key="btn_submit_disabled")
    else:
        run_button(
            "submit",
            "Submit these trades",
            lambda: run_streaming(
                [
                    "python",
                    "-m",
                    "durable.execution.submit",
                    "--proposal",
                    chosen,
                    "--i-have-read-the-proposal",
                ]
            ),
        )

    st.divider()
    st.caption(
        "Prefer the plain command-line instructions instead? This just prints them, it doesn't "
        "submit anything:"
    )
    run_button("submit_help", "Show the manual command", lambda: run_make("submit"), primary=False)


def page_report() -> None:
    step_header(
        16,
        TOTAL_STEPS,
        "Performance Report",
        "Generates a performance report: returns, risk, and how it compares to a plain index "
        "fund benchmark.",
    )
    report_type = st.selectbox(
        "Report type", REPORT_TYPES, index=REPORT_TYPES.index("quarterly"), key="report_type"
    )
    run_button("report", "Generate report", lambda: run_make("report", {"TYPE": report_type}))


def page_research_export() -> None:
    step_header(
        17,
        TOTAL_STEPS,
        "Research Export",
        "Exports a full research bulletin — JSON, CSV, LaTeX tables, and 300dpi figures — for "
        "deeper analysis outside this program.",
    )
    run_button("research_export", "Export research bulletin", lambda: run_make("research-export"))


def page_tax_review() -> None:
    step_header(
        18,
        TOTAL_STEPS,
        "Tax Review",
        "Reviews your tax lots for loss-harvesting candidates, checks for wash-sale violations, "
        "and estimates the tax alpha this system has generated.",
    )
    run_button("tax_review", "Run tax review", lambda: run_make("tax-review"))


def page_journal() -> None:
    step_header(
        19,
        TOTAL_STEPS,
        "Decision Journal",
        "Scores how well-calibrated your past predictions have been — not just whether you were "
        "right, but whether your stated confidence matched your accuracy.",
    )
    run_button("journal", "Score journal calibration", lambda: run_make("journal"))


def page_reproduce() -> None:
    step_header(
        20,
        TOTAL_STEPS,
        "Reproduce a Past Report",
        "Regenerates a prior report byte-for-byte from a given git commit, to prove the system's "
        "output is fully reproducible and not dependent on hidden state.",
    )
    commit = st.text_input(
        "Git commit hash", key="reproduce_commit", placeholder="abc1234"
    ).strip()
    disabled = not commit
    st.button(
        "Reproduce report",
        key="btn_reproduce_disabled_hint",
        disabled=True,
        help="paste a commit hash first",
    ) if disabled else run_button(
        "reproduce", "Reproduce report", lambda: run_make("reproduce", {"COMMIT": commit})
    )


PAGES: dict[str, dict] = {
    "🏁 Get Started": {
        "Welcome & Workflow Guide": page_welcome,
        "Setup Check & Install": page_setup,
        "Run Tests (Health Check)": page_test,
    },
    "📁 Files & Outputs": {
        "Browse Files": page_files,
    },
    "📊 Data": {
        "Update Market Data (Ingest)": page_ingest,
        "Data Safety Check (Leakage Audit)": page_leakage_audit,
        "Dry-Run Simulation": page_simulate,
    },
    "🔬 Research & Backtesting": {
        "Score Companies": page_score,
        "Test a Factor (IC)": page_ic,
        "Backtest the Strategy": page_backtest,
        "Validate Robustness (CPCV)": page_cpcv,
    },
    "🔎 Discovery (Sleeve E)": {
        "Discover New Ideas": page_discover,
        "Research One Stock (Dossier)": page_dossier,
        "Extract Filing Data (LLM)": page_extract,
    },
    "💰 Trading": {
        "Propose Trades": page_propose,
        "Review & Submit Trades": page_submit,
    },
    "📈 Reports, Tax & Journal": {
        "Performance Report": page_report,
        "Research Export": page_research_export,
        "Tax Review": page_tax_review,
        "Decision Journal": page_journal,
        "Reproduce a Past Report": page_reproduce,
    },
}


def main() -> None:
    st.sidebar.title("Durable Alpha")
    st.sidebar.caption(
        "Every command below has a command-line twin. See each page for the exact command."
    )
    section = st.sidebar.selectbox("Section", list(PAGES.keys()), key="nav_section")
    page_label = st.sidebar.radio("Step", list(PAGES[section].keys()), key=f"nav_page_{section}")
    st.sidebar.divider()
    st.sidebar.caption(f"Project folder:\n`{PROJECT_ROOT}`")

    PAGES[section][page_label]()


if __name__ == "__main__":
    main()
