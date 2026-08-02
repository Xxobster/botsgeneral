"""Resolved research-data paths (override with TRADING_DATA_ROOT)."""
from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_ROOT = Path(r"D:\projectsdata")


def trading_data_root() -> Path:
    raw = os.environ.get("TRADING_DATA_ROOT")
    return Path(raw) if raw else _DEFAULT_ROOT


def candles_root() -> Path:
    return trading_data_root() / "candles"


def market_ohlcv_db() -> Path:
    return candles_root() / "market_ohlcv.sqlite"
