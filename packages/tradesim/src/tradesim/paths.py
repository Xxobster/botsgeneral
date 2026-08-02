"""Resolved research/backtest paths (override with TRADING_DATA_ROOT)."""
from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_ROOT = Path(r"D:\projectsdata")


def trading_data_root() -> Path:
    raw = os.environ.get("TRADING_DATA_ROOT")
    return Path(raw) if raw else _DEFAULT_ROOT


def candles_root() -> Path:
    return trading_data_root() / "candles"


def bybit_instruments_db() -> Path:
    return candles_root() / "bybit_instruments.sqlite"


def backtests_root() -> Path:
    return trading_data_root() / "backtests"


def tradesim_store_path() -> Path:
    return backtests_root() / "tradesim_runs.sqlite"


def tradesim_reports_dir() -> Path:
    return backtests_root() / "reports"


def tradesim_runs_dir() -> Path:
    return backtests_root() / "runs"
