"""Resolved indicator warehouse paths (override with TRADING_DATA_ROOT)."""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_ROOT = Path(r"D:\projectsdata")


def trading_data_root() -> Path:
    raw = os.environ.get("TRADING_DATA_ROOT")
    return Path(raw) if raw else _DEFAULT_ROOT


def indicators_root() -> Path:
    return trading_data_root() / "indicators"


def indicators_db() -> Path:
    """Canonical SQLite warehouse programs open and copy from."""
    return indicators_root() / "indicators.sqlite"


def candles_db() -> Path:
    """Research OHLCV source (same as market_data)."""
    return trading_data_root() / "candles" / "market_ohlcv.sqlite"
