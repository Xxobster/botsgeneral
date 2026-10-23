"""SQLite store for shared research open interest at D:\\projectsdata\\candles."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Iterable

import pandas as pd

from market_data.paths import market_oi_db

DEFAULT_OI_DB_PATH = market_oi_db()

SCHEMA = """
CREATE TABLE IF NOT EXISTS market_oi (
  exchange TEXT NOT NULL,
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  ts_ms INTEGER NOT NULL,
  oi REAL,
  oi_usd REAL,
  oi_sum REAL,
  count_toptrader_ls_ratio REAL,
  sum_toptrader_ls_ratio REAL,
  count_ls_ratio REAL,
  sum_taker_ls_vol_ratio REAL,
  source_endpoint TEXT,
  downloaded_at INTEGER NOT NULL,
  PRIMARY KEY (exchange, symbol, timeframe, ts_ms)
);
CREATE INDEX IF NOT EXISTS idx_oi_lookup
  ON market_oi(symbol, timeframe, ts_ms);
CREATE INDEX IF NOT EXISTS idx_oi_exchange
  ON market_oi(exchange, symbol, timeframe, ts_ms);

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


class ResearchOIDB:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else DEFAULT_OI_DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), timeout=120, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA temp_store=MEMORY")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self._conn.commit()

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def max_ts_ms(self, exchange: str, symbol: str, timeframe: str) -> int | None:
        row = self._conn.execute(
            "SELECT MAX(ts_ms) FROM market_oi "
            "WHERE exchange=? AND symbol=? AND timeframe=?",
            (exchange, symbol, timeframe),
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else None

    def min_ts_ms(self, exchange: str, symbol: str, timeframe: str) -> int | None:
        row = self._conn.execute(
            "SELECT MIN(ts_ms) FROM market_oi "
            "WHERE exchange=? AND symbol=? AND timeframe=?",
            (exchange, symbol, timeframe),
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else None

    def upsert_df(
        self,
        df: pd.DataFrame,
        *,
        exchange: str,
        symbol: str,
        timeframe: str,
        source_endpoint: str | None = None,
    ) -> int:
        """Upsert OI rows. Requires ts_ms; optional oi / oi_usd / oi_sum / ratio columns."""
        if df is None or df.empty:
            return 0
        data = df.copy()
        if "ts_ms" not in data.columns:
            raise ValueError("OI DataFrame must include ts_ms")
        data["ts_ms"] = pd.to_numeric(data["ts_ms"], errors="coerce")
        data = data.dropna(subset=["ts_ms"])
        data["ts_ms"] = data["ts_ms"].astype("int64")
        data = data.drop_duplicates(subset=["ts_ms"], keep="last")

        now = int(time.time() * 1000)
        cols_optional = (
            "oi",
            "oi_usd",
            "oi_sum",
            "count_toptrader_ls_ratio",
            "sum_toptrader_ls_ratio",
            "count_ls_ratio",
            "sum_taker_ls_vol_ratio",
        )
        rows: list[tuple] = []
        for rec in data.to_dict("records"):
            rows.append(
                (
                    exchange,
                    symbol.upper(),
                    timeframe,
                    int(rec["ts_ms"]),
                    _f(rec.get("oi")),
                    _f(rec.get("oi_usd")),
                    _f(rec.get("oi_sum")),
                    _f(rec.get("count_toptrader_ls_ratio")),
                    _f(rec.get("sum_toptrader_ls_ratio")),
                    _f(rec.get("count_ls_ratio")),
                    _f(rec.get("sum_taker_ls_vol_ratio")),
                    source_endpoint,
                    now,
                )
            )
        self._conn.executemany(
            """
            INSERT INTO market_oi(
              exchange, symbol, timeframe, ts_ms,
              oi, oi_usd, oi_sum,
              count_toptrader_ls_ratio, sum_toptrader_ls_ratio,
              count_ls_ratio, sum_taker_ls_vol_ratio,
              source_endpoint, downloaded_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(exchange, symbol, timeframe, ts_ms) DO UPDATE SET
              oi=excluded.oi,
              oi_usd=excluded.oi_usd,
              oi_sum=COALESCE(excluded.oi_sum, market_oi.oi_sum),
              count_toptrader_ls_ratio=COALESCE(excluded.count_toptrader_ls_ratio, market_oi.count_toptrader_ls_ratio),
              sum_toptrader_ls_ratio=COALESCE(excluded.sum_toptrader_ls_ratio, market_oi.sum_toptrader_ls_ratio),
              count_ls_ratio=COALESCE(excluded.count_ls_ratio, market_oi.count_ls_ratio),
              sum_taker_ls_vol_ratio=COALESCE(excluded.sum_taker_ls_vol_ratio, market_oi.sum_taker_ls_vol_ratio),
              source_endpoint=COALESCE(excluded.source_endpoint, market_oi.source_endpoint),
              downloaded_at=excluded.downloaded_at
            """,
            rows,
        )
        self._conn.commit()
        return len(rows)

    def coverage(self) -> pd.DataFrame:
        q = """
        SELECT exchange, symbol, timeframe,
               COUNT(*) AS bars,
               MIN(ts_ms) AS first_ts,
               MAX(ts_ms) AS last_ts
        FROM market_oi
        GROUP BY exchange, symbol, timeframe
        ORDER BY exchange, symbol, timeframe
        """
        return pd.read_sql_query(q, self._conn)


def _f(v) -> float | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
