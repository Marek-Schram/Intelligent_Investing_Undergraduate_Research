"""Shared config.yaml loader. docs/01 ARCHITECTURE.

Every CLI entry point needs the same strategy settings (universe filters, position sizing,
rebalance cadence, safety flags). This is the one place that reads the file, so there is
exactly one code path to audit for the `live_trading_approved` safety flag.

Data source: config/config.yaml (gitignored; config/config.example.yaml is the checked-in
template). Not point-in-time data — this is static strategy configuration, not a market
observation, so `available_at` does not apply.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = PROJECT_ROOT / "config" / "config.yaml"
CONFIG_EXAMPLE = PROJECT_ROOT / "config" / "config.example.yaml"


class ConfigError(Exception):
    """Raised when config/config.yaml is missing or unreadable."""


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load and parse config.yaml. Falls back to config.example.yaml only for its schema
    shape in tests; real runs must have a real config.yaml (created via the Setup page)."""
    config_path = Path(path) if path is not None else CONFIG_FILE
    if not config_path.is_file():
        raise ConfigError(
            f"{config_path} does not exist. Run `make setup` or use the Setup page in the GUI "
            "to create it from config.example.yaml first."
        )
    with config_path.open() as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ConfigError(f"{config_path} did not parse to a mapping.")
    return data


def is_live_trading_approved(config: dict[str, Any]) -> bool:
    return bool(config.get("live_trading_approved", False))
