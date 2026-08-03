"""Load / refresh research candles for indicator computation."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pandas as pd

from .paths import candles_db

# Structure-friendly defaults (15m available via --timeframes; 1m/5m via 'all').
DEFAULT_STRUCTURE_TIMEFRAMES: tuple[str, ...] = ("1h", "4h", "1d", "1w")


def open_candle_db(path: str | Path | None = None):
    from market_data import ResearchCandleDB

    return ResearchCandleDB(path or candles_db())


def list_series(
    candle_db=None,
    *,
    symbols: Sequence[str] | None = None,
    timeframes: Sequence[str] | None = DEFAULT_STRUCTURE_TIMEFRAMES,
    sources: Sequence[str] | None = None,
    min_bars: int = 50,
) -> pd.DataFrame:
    """Coverage rows from the research OHLCV warehouse, filtered for structure work."""
    own = candle_db is None
    db = candle_db or open_candle_db()
    try:
        cov = db.coverage()
    finally:
        if own:
            db.close()
    if cov.empty:
        return cov
    if symbols:
        sym = {s.upper() for s in symbols}
        cov = cov[cov["symbol"].str.upper().isin(sym)]
    if timeframes:
        tf = {t.lower() for t in timeframes}
        cov = cov[cov["timeframe"].str.lower().isin(tf)]
    if sources:
        src = set(sources)
        cov = cov[cov["source"].isin(src)]
    cov = cov[cov["bars"] >= int(min_bars)]
    return cov.reset_index(drop=True)


def load_candles(
    symbol: str,
    timeframe: str,
    *,
    source: str | None = None,
    candle_db=None,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> pd.DataFrame:
    """Fetch OHLCV for one series from ``market_ohlcv.sqlite``."""
    own = candle_db is None
    db = candle_db or open_candle_db()
    try:
        return db.load(
            symbol, timeframe, source=source, start_ms=start_ms, end_ms=end_ms
        )
    finally:
        if own:
            db.close()


def refresh_candles(
    symbols: Sequence[str] | None = None,
    timeframes: Sequence[str] | None = None,
    *,
    price_types: tuple[str, ...] = ("last", "mark"),
    only: Sequence[str] | None = None,
) -> int:
    """Pull latest research candles via market_data (optional network)."""
    from market_data.download_all import run as download_run

    return download_run(
        only=set(only) if only else None,
        symbols=set(symbols) if symbols else None,
        timeframes=set(timeframes) if timeframes else None,
        price_types=price_types,
        incremental=True,
    )
