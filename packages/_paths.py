"""Shared path resolver used by packages before they are fully importable.

Prefer importing ``tradesim.paths`` / ``market_data.paths`` from installed packages.
This module exists only as a bootstrap helper during the workspace transition.
"""
from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_ROOT = Path(r"D:\projectsdata")


def trading_data_root() -> Path:
    raw = os.environ.get("TRADING_DATA_ROOT")
    if raw:
        return Path(raw)
    return _DEFAULT_ROOT


def candles_root() -> Path:
    return trading_data_root() / "candles"


def market_ohlcv_db() -> Path:
    return candles_root() / "market_ohlcv.sqlite"


def bybit_instruments_db() -> Path:
    return candles_root() / "bybit_instruments.sqlite"


def indicators_root() -> Path:
    return trading_data_root() / "indicators"


def indicators_db() -> Path:
    return indicators_root() / "indicators.sqlite"


def backtests_root() -> Path:
    return trading_data_root() / "backtests"


def tradesim_store_path() -> Path:
    return backtests_root() / "tradesim_runs.sqlite"


def tradesim_reports_dir() -> Path:
    return backtests_root() / "reports"


def tradesim_runs_dir() -> Path:
    return backtests_root() / "runs"
