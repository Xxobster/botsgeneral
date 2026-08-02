"""ts_ms surface — formerly botsgeneral.reader."""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import pandas as pd

from live_candles.models import TF_MS, normalize_symbol, normalize_timeframe

DEFAULT_DB = "/var/lib/botsgeneral/shared_candles.db"


def shared_db_path(explicit: str | Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get("SHARED_CANDLES_DB") or os.environ.get("BOTSGENERAL_DB")
    if env:
        return Path(env)
    return Path(DEFAULT_DB)


def load_ohlcv(
    exchange: str,
    symbol: str,
    timeframe: str,
    *,
    db_path: str | Path | None = None,
    limit: int | None = None,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> pd.DataFrame:
    path = shared_db_path(db_path)
    ex = str(exchange).lower().strip()
    sym = normalize_symbol(symbol)
    tf = normalize_timeframe(timeframe)
    clauses = ["exchange = ?", "symbol = ?", "timeframe = ?"]
    params: list[Any] = [ex, sym, tf]
    if start_ms is not None:
        clauses.append("ts_ms >= ?")
        params.append(int(start_ms))
    if end_ms is not None:
        clauses.append("ts_ms <= ?")
        params.append(int(end_ms))
    where = " AND ".join(clauses)
    sql = f"""
        SELECT ts_ms, open, high, low, close, volume,
               quote_volume, trades, taker_buy_base, taker_buy_quote, updated_at_ms
        FROM candles
        WHERE {where}
        ORDER BY ts_ms ASC
    """
    if limit is not None and int(limit) > 0:
        sql = f"""
            SELECT * FROM (
                SELECT ts_ms, open, high, low, close, volume,
                       quote_volume, trades, taker_buy_base, taker_buy_quote, updated_at_ms
                FROM candles
                WHERE {where}
                ORDER BY ts_ms DESC
                LIMIT {int(limit)}
            ) ORDER BY ts_ms ASC
        """
    with sqlite3.connect(str(path), timeout=30) as conn:
        df = pd.read_sql_query(sql, conn, params=params)
    if df.empty:
        return df
    df["ts_ms"] = df["ts_ms"].astype("int64")
    return df


def newest_ts_ms(
    exchange: str,
    symbol: str,
    timeframe: str,
    *,
    db_path: str | Path | None = None,
) -> int | None:
    path = shared_db_path(db_path)
    with sqlite3.connect(str(path), timeout=30) as conn:
        row = conn.execute(
            """
            SELECT MAX(ts_ms) FROM candles
            WHERE exchange=? AND symbol=? AND timeframe=?
            """,
            (str(exchange).lower(), normalize_symbol(symbol), normalize_timeframe(timeframe)),
        ).fetchone()
    if not row or row[0] is None:
        return None
    return int(row[0])


def is_fresh(
    exchange: str,
    symbol: str,
    timeframe: str,
    *,
    db_path: str | Path | None = None,
    max_lag_bars: float = 2.0,
    now_ms: int | None = None,
) -> bool:
    tf = normalize_timeframe(timeframe)
    tf_ms = int(TF_MS.get(tf) or 0)
    if tf_ms <= 0:
        return False
    last = newest_ts_ms(exchange, symbol, tf, db_path=db_path)
    if last is None:
        return False
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    age_after_close = now - (last + tf_ms)
    return age_after_close <= max_lag_bars * tf_ms
