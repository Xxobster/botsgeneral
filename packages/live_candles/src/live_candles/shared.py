"""timestamp-datetime surface — formerly per-project shared_candles.py."""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from pathlib import Path

import pandas as pd

from live_candles.models import TF_MS, normalize_symbol, normalize_timeframe
from live_candles.reader import shared_db_path

log = logging.getLogger(__name__)

# After a bar closes, allow the collector this long to write it before
# treating the gap as a hard missing-bar fault (bot still waits either way).
DEFAULT_CLOSE_GRACE_MS = 180_000


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
    close_grace_ms: int | None = None,
) -> tuple[bool, int | None, str]:
    """Return whether the latest *fully closed* bar is present in the shared DB.

    Candle ``ts_ms`` values are bar **open** times. The open of the newest bar
    that should already be closed is ``floor(now/tf)*tf - tf``.

    Previous logic used ``now - last_open`` against ``2*tf``, which flips to
    "stale" for ~1–2s every hour while the collector is still writing the
    just-closed bar (``last`` still one bar behind → lag just over ``2*tf``).
    That is a false stale: we only need ``last >= expected_closed_open``.
    """
    step = interval_ms(interval)
    if step <= 0:
        return False, None, "bad timeframe"
    last = latest_ts_ms(symbol, interval, exchange=exchange, db_path=db_path)
    if last is None:
        return False, None, "no candles in shared DB"
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    expected = (now // step) * step - step
    grace = (
        int(close_grace_ms)
        if close_grace_ms is not None
        else int(os.environ.get("CANDLES_CLOSE_GRACE_MS", str(DEFAULT_CLOSE_GRACE_MS)))
    )
    if last >= expected:
        age_after_close = now - (last + step)
        max_age = int(step * max_age_mult)
        if age_after_close > max_age:
            return (
                False,
                last,
                f"stale_after_close last_ts_ms={last} age_ms={age_after_close} max_ms={max_age}",
            )
        return True, last, "ok"

    ms_since_close = now - (expected + step)
    if 0 <= ms_since_close <= grace:
        return (
            False,
            last,
            (
                f"awaiting_just_closed expected_ts_ms={expected} last_ts_ms={last} "
                f"ms_since_close={ms_since_close} grace_ms={grace}"
            ),
        )
    return (
        False,
        last,
        (
            f"missing_closed_bar expected_ts_ms={expected} last_ts_ms={last} "
            f"behind_ms={expected - last}"
        ),
    )
