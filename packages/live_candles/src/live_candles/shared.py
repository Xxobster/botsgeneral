"""timestamp-datetime surface — formerly per-project shared_candles.py."""
from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

import pandas as pd

from live_candles.models import TF_MS, normalize_symbol, normalize_timeframe
from live_candles.reader import shared_db_path

log = logging.getLogger(__name__)


def interval_ms(interval: str) -> int:
    return TF_MS.get(normalize_timeframe(interval), 300_000)


def load_candles(
    symbol: str,
    interval: str,
    *,
    exchange: str = "bybit",
    db_path: Path | str | None = None,
) -> pd.DataFrame:
    path = Path(db_path) if db_path else shared_db_path()
    empty = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    if not path.exists():
        log.error("Shared candles DB missing: %s", path)
        return empty

    sym = normalize_symbol(symbol)
    tf = normalize_timeframe(interval)
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30) as conn:
            df = pd.read_sql(
                """
                SELECT ts_ms, open, high, low, close, volume
                FROM candles
                WHERE exchange=? AND symbol=? AND timeframe=?
                ORDER BY ts_ms
                """,
                conn,
                params=(exchange.lower(), sym, tf),
            )
    except Exception:
        log.exception(
            "Failed reading shared candles %s %s %s from %s", exchange, sym, tf, path
        )
        return empty

    if df.empty:
        log.error("No shared candles for %s %s %s in %s", exchange, sym, tf, path)
        return empty

    df["timestamp"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    return df[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


def latest_ts_ms(
    symbol: str,
    interval: str,
    *,
    exchange: str = "bybit",
    db_path: Path | str | None = None,
) -> int | None:
    path = Path(db_path) if db_path else shared_db_path()
    if not path.exists():
        return None
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30) as conn:
            row = conn.execute(
                """
                SELECT MAX(ts_ms) FROM candles
                WHERE exchange=? AND symbol=? AND timeframe=?
                """,
                (exchange.lower(), normalize_symbol(symbol), normalize_timeframe(interval)),
            ).fetchone()
        return int(row[0]) if row and row[0] is not None else None
    except Exception:
        log.exception("latest_ts_ms failed for %s %s", symbol, interval)
        return None


def candles_fresh(
    symbol: str,
    interval: str,
    *,
    exchange: str = "bybit",
    db_path: Path | str | None = None,
    max_age_mult: float = 2.0,
    now_ms: int | None = None,
) -> tuple[bool, int | None, str]:
    last = latest_ts_ms(symbol, interval, exchange=exchange, db_path=db_path)
    if last is None:
        return False, None, "no candles in shared DB"
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    max_lag = int(interval_ms(interval) * max_age_mult)
    lag = now - last
    if lag > max_lag:
        return False, last, f"stale last_ts_ms={last} lag_ms={lag} max_ms={max_lag}"
    return True, last, "ok"
