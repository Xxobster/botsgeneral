"""Update indicator warehouse for one series or the full research universe."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import pandas as pd

from .candles import (
    DEFAULT_STRUCTURE_TIMEFRAMES,
    list_series,
    load_candles,
    open_candle_db,
    refresh_candles,
)
from .compute import DEFAULT_SWING_LEFT, DEFAULT_SWING_RIGHT, compute_structure
from .paths import indicators_db
from .store import IndicatorDB


@dataclass(frozen=True)
class UpdateResult:
    source: str
    symbol: str
    timeframe: str
    n_bars: int
    n_swings: int
    counts: dict[str, int]
    error: str = ""


def update_series(
    symbol: str,
    timeframe: str,
    *,
    source: str | None = None,
    swing_left: int = DEFAULT_SWING_LEFT,
    swing_right: int = DEFAULT_SWING_RIGHT,
    indicator_db: IndicatorDB | None = None,
    candle_db=None,
    ohlcv: pd.DataFrame | None = None,
) -> UpdateResult:
    """Compute structure+fib features and upsert one series into the warehouse."""
    own_ind = indicator_db is None
    own_cndl = candle_db is None and ohlcv is None
    ind = indicator_db or IndicatorDB()
    cdb = None if ohlcv is not None else (candle_db or open_candle_db())
    try:
        df = ohlcv if ohlcv is not None else load_candles(
            symbol, timeframe, source=source, candle_db=cdb
        )
        if df is None or df.empty:
            return UpdateResult(
                source=source or "",
                symbol=symbol,
                timeframe=timeframe,
                n_bars=0,
                n_swings=0,
                counts={},
                error="no candles",
            )
        # If source not specified and load returned mixed sources, take the dominant.
        src = source or str(df["source"].iloc[0])
        if source is None and df["source"].nunique() > 1:
            # Prefer binance last over mark when mixed accidentally.
            if (df["source"] == "binance").any():
                df = df[df["source"] == "binance"].copy()
                src = "binance"
            else:
                src = str(df["source"].mode().iloc[0])
                df = df[df["source"] == src].copy()
        bundle = compute_structure(
            df,
            source=src,
            symbol=symbol,
            timeframe=timeframe,
            swing_left=swing_left,
            swing_right=swing_right,
        )
        counts = ind.upsert_bundle(bundle)
        return UpdateResult(
            source=src,
            symbol=symbol,
            timeframe=timeframe,
            n_bars=bundle.n_bars,
            n_swings=bundle.n_swings,
            counts=counts,
        )
    finally:
        if own_ind:
            ind.close()
        if own_cndl and cdb is not None:
            cdb.close()


def update_all(
    *,
    symbols: Sequence[str] | None = None,
    timeframes: Sequence[str] | None = DEFAULT_STRUCTURE_TIMEFRAMES,
    sources: Sequence[str] | None = None,
    swing_left: int = DEFAULT_SWING_LEFT,
    swing_right: int = DEFAULT_SWING_RIGHT,
    min_bars: int = 50,
    refresh: bool = False,
    indicator_path: str | Path | None = None,
    candle_path: str | Path | None = None,
    progress: bool = True,
) -> list[UpdateResult]:
    """Recompute indicators for every matching series in the candle warehouse."""
    if refresh:
        refresh_candles(symbols=symbols, timeframes=timeframes)

    cdb = open_candle_db(candle_path)
    ind = IndicatorDB(indicator_path or indicators_db())
    results: list[UpdateResult] = []
    try:
        cov = list_series(
            cdb,
            symbols=symbols,
            timeframes=timeframes,
            sources=sources,
            min_bars=min_bars,
        )
        total = len(cov)
        for i, row in enumerate(cov.itertuples(index=False), start=1):
            if progress:
                print(
                    f"[{i}/{total}] {row.source} {row.symbol} {row.timeframe} "
                    f"({row.bars} bars)…",
                    flush=True,
                )
            try:
                res = update_series(
                    row.symbol,
                    row.timeframe,
                    source=row.source,
                    swing_left=swing_left,
                    swing_right=swing_right,
                    indicator_db=ind,
                    candle_db=cdb,
                )
            except Exception as exc:  # noqa: BLE001 — continue universe update
                res = UpdateResult(
                    source=str(row.source),
                    symbol=str(row.symbol),
                    timeframe=str(row.timeframe),
                    n_bars=0,
                    n_swings=0,
                    counts={},
                    error=str(exc),
                )
            results.append(res)
            if progress and res.error:
                print(f"  ERROR: {res.error}", flush=True)
            elif progress:
                print(
                    f"  ok bars={res.n_bars} swings={res.n_swings} "
                    f"features={res.counts.get('bar_features', 0)}",
                    flush=True,
                )
        ind.set_meta("last_update_all_ms", str(int(pd.Timestamp.utcnow().timestamp() * 1000)))
        ind.set_meta("last_update_all_series", str(len(results)))
    finally:
        ind.close()
        cdb.close()
    return results
