"""Shared Fibonacci price-structure indicator warehouse.

Programs must use this package (not private swing/fib helpers) so every repository
reads the same confirmed swings, HH/HL structure, leg retracements and S/R distances.

    from indicators.ensure_source import prefer_botsgeneral_indicators
    prefer_botsgeneral_indicators()

    from indicators import IndicatorDB, compute_structure, update_all, update_series

Warehouse: ``D:\\projectsdata\\indicators\\indicators.sqlite``
Candle source: ``D:\\projectsdata\\candles\\market_ohlcv.sqlite``
"""

from __future__ import annotations

from .candles import (
    DEFAULT_STRUCTURE_TIMEFRAMES,
    list_series,
    load_candles,
    open_candle_db,
    refresh_candles,
)
from .compute import (
    DEFAULT_SWING_LEFT,
    DEFAULT_SWING_RIGHT,
    StructureBundle,
    compute_structure,
    tables_from_bundle,
)
from .ensure_source import assert_botsgeneral_indicators, prefer_botsgeneral_indicators
from .fibonacci import (
    FIB_ALL,
    FIB_EXTENSION,
    FIB_RETRACEMENT,
    fib_label,
    fib_levels,
    nearest_fib,
    retracement_ratio,
)
from .levels import Level, levels_from_swings, nearest_levels_at_bars
from .paths import candles_db, indicators_db, indicators_root
from .store import IndicatorDB
from .structure import Leg, StructureEvent, build_legs, label_structure
from .swings import Swing, find_swings
from .update import UpdateResult, update_all, update_series

__all__ = [
    "DEFAULT_STRUCTURE_TIMEFRAMES",
    "DEFAULT_SWING_LEFT",
    "DEFAULT_SWING_RIGHT",
    "FIB_ALL",
    "FIB_EXTENSION",
    "FIB_RETRACEMENT",
    "IndicatorDB",
    "Leg",
    "Level",
    "StructureBundle",
    "StructureEvent",
    "Swing",
    "UpdateResult",
    "assert_botsgeneral_indicators",
    "build_legs",
    "candles_db",
    "compute_structure",
    "fib_label",
    "fib_levels",
    "find_swings",
    "indicators_db",
    "indicators_root",
    "label_structure",
    "levels_from_swings",
    "list_series",
    "load_candles",
    "nearest_fib",
    "nearest_levels_at_bars",
    "open_candle_db",
    "prefer_botsgeneral_indicators",
    "refresh_candles",
    "retracement_ratio",
    "tables_from_bundle",
    "update_all",
    "update_series",
]
