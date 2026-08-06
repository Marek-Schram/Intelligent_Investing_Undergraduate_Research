"""Runs the project's `make` targets as subprocesses and streams their output.

The GUI never re-implements any command. Every button here shells out to the exact
same `make <target>` (or, for the human-gated submit step, the exact same
`python -m durable.execution.submit ...`) that a person would type at a terminal —
so GUI behavior and CLI behavior can never drift apart.
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Iterable
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def build_env() -> dict[str, str]:
    """Environment for subprocesses: prefer the project's own virtualenv on PATH."""
    env = os.environ.copy()
    venv_bin = PROJECT_ROOT / ".venv" / "bin"
    if venv_bin.is_dir():
        env["PATH"] = f"{venv_bin}{os.pathsep}{env.get('PATH', '')}"
        env["VIRTUAL_ENV"] = str(PROJECT_ROOT / ".venv")
    return env


def command_text(cmd: Iterable[str]) -> str:
    return " ".join(cmd)


def run_streaming(cmd: list[str], *, cwd: Path = PROJECT_ROOT) -> tuple[int, str]:
    """Run `cmd`, streaming stdout+stderr into the page live. Returns (exit_code, full_output)."""
    st.caption(f"Running: `{command_text(cmd)}`")
    output_placeholder = st.empty()
    lines: list[str] = []
    last_render = 0.0

    try:
        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=build_env(),
        )
    except FileNotFoundError as exc:
        st.error(f"Could not start `{cmd[0]}`: {exc}")
        return 1, ""

    assert process.stdout is not None
    for line in process.stdout:
        lines.append(line)
        now = time.monotonic()
        if now - last_render > 0.15 or len(lines) < 5:
            output_placeholder.code("".join(lines[-500:]) or "(no output yet)", language="text")
            last_render = now
    process.wait()
    output_placeholder.code(
        "".join(lines[-500:]) or "(command finished with no output)", language="text"
    )

    if process.returncode == 0:
        st.success("Finished successfully (exit code 0).")
    else:
        st.error(f"Command exited with code {process.returncode}. See the log above for details.")
    return process.returncode, "".join(lines)


def run_make(target: str, variables: dict[str, str] | None = None) -> tuple[int, str]:
    cmd = ["make", target]
    for key, value in (variables or {}).items():
        if value not in (None, ""):
            cmd.append(f"{key}={value}")
    return run_streaming(cmd)


def list_recent_files(
    directory: Path, patterns: tuple[str, ...] = ("*",), limit: int = 25
) -> list[Path]:
    if not directory.is_dir():
        return []
    files: list[Path] = []
    for pattern in patterns:
        files.extend(p for p in directory.glob(pattern) if p.is_file())
    files = sorted(set(files), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]
