"""SQLite store for shared research OHLCV at D:\\projectsdata\\candles."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Iterable

import pandas as pd

from market_data.timestamps import to_ts_ms
from market_data.universe import DEFAULT_DB

DEFAULT_DB_PATH = Path(DEFAULT_DB)

SCHEMA = """
CREATE TABLE IF NOT EXISTS market_ohlcv (
  source TEXT NOT NULL,
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  ts_ms INTEGER NOT NULL,
  open REAL NOT NULL,
  high REAL NOT NULL,
  low REAL NOT NULL,
  close REAL NOT NULL,
  volume REAL,
  price_type TEXT,
  product TEXT,
  source_endpoint TEXT,
  is_complete INTEGER NOT NULL DEFAULT 1,
  downloaded_at INTEGER NOT NULL,
  PRIMARY KEY (source, symbol, timeframe, ts_ms)
);
CREATE INDEX IF NOT EXISTS idx_market_lookup
  ON market_ohlcv(symbol, timeframe, ts_ms);
CREATE INDEX IF NOT EXISTS idx_market_source
  ON market_ohlcv(source, symbol, timeframe, ts_ms);

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


class ResearchCandleDB:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else DEFAULT_DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), timeout=120, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA temp_store=MEMORY")
        self._conn.executescript(SCHEMA)
        self._migrate_schema()
        self._conn.commit()

    def _migrate_schema(self) -> None:
        """Apply additive metadata migrations to existing warehouse DBs."""
        columns = {
            str(row[1])
            for row in self._conn.execute("PRAGMA table_info(market_ohlcv)").fetchall()
        }
        if "product" not in columns:
            self._conn.execute("ALTER TABLE market_ohlcv ADD COLUMN product TEXT")
        if "source_endpoint" not in columns:
            self._conn.execute("ALTER TABLE market_ohlcv ADD COLUMN source_endpoint TEXT")
        migration_key = "schema_migration_engine_005_mark_provenance"
        migrated = self._conn.execute(
            "SELECT value FROM meta WHERE key=?", (migration_key,)
        ).fetchone()
        if not migrated:
            self._conn.execute(
                """
                UPDATE market_ohlcv
                SET price_type='mark_price',
                    product='USDⓈ-M',
                    source_endpoint='/fapi/v1/markPriceKlines'
                WHERE source='binance_mark'
                """
            )
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?)",
                (migration_key, "1"),
            )

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

    def upsert_df(
        self,
        df: pd.DataFrame,
        *,
        source: str,
        symbol: str,
        timeframe: str,
        price_type: str | None = None,
        product: str | None = None,
        source_endpoint: str | None = None,
        is_complete: int = 1,
    ) -> int:
        """Upsert OHLCV DataFrame with columns ts_ms|timestamp, open, high, low, close, [volume]."""
        if df is None or df.empty:
            return 0
        data = df.copy()
        if "ts_ms" not in data.columns:
            if "timestamp" not in data.columns:
                raise ValueError("DataFrame needs ts_ms or timestamp")
            data["ts_ms"] = to_ts_ms(data["timestamp"])
        now = int(time.time() * 1000)
        vol = data["volume"].astype(float).fillna(0.0).to_numpy() if "volume" in data.columns else [None] * len(data)
        rows = list(
            zip(
                [source] * len(data),
                [symbol] * len(data),
                [timeframe] * len(data),
                data["ts_ms"].astype("int64").to_numpy().tolist(),
                data["open"].astype(float).to_numpy().tolist(),
                data["high"].astype(float).to_numpy().tolist(),
                data["low"].astype(float).to_numpy().tolist(),
                data["close"].astype(float).to_numpy().tolist(),
                list(vol) if not isinstance(vol, list) else vol,
                [price_type] * len(data),
                [product] * len(data),
                [source_endpoint] * len(data),
                [is_complete] * len(data),
                [now] * len(data),
            )
        )
        self._conn.executemany(
            """
            INSERT INTO market_ohlcv (
              source, symbol, timeframe, ts_ms, open, high, low, close, volume,
              price_type, product, source_endpoint, is_complete, downloaded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, symbol, timeframe, ts_ms) DO UPDATE SET
              open=excluded.open,
              high=excluded.high,
              low=excluded.low,
              close=excluded.close,
              volume=excluded.volume,
              price_type=excluded.price_type,
              product=excluded.product,
              source_endpoint=excluded.source_endpoint,
              is_complete=excluded.is_complete,
              downloaded_at=excluded.downloaded_at
            """,
            rows,
        )
        self._conn.commit()
        return len(rows)

    def load(
        self,
        symbol: str,
        timeframe: str,
        source: str | None = None,
        *,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> pd.DataFrame:
        clauses = ["symbol=?", "timeframe=?"]
        params: list = [symbol, timeframe]
        if source:
            clauses.append("source=?")
            params.append(source)
        if start_ms is not None:
            clauses.append("ts_ms>=?")
            params.append(start_ms)
        if end_ms is not None:
            clauses.append("ts_ms<=?")
            params.append(end_ms)
        where = " AND ".join(clauses)
        sql = (
            f"SELECT source, symbol, timeframe, ts_ms, open, high, low, close, volume, "
            f"price_type, product, source_endpoint "
            f"FROM market_ohlcv WHERE {where} ORDER BY ts_ms"
        )
        df = pd.read_sql_query(sql, self._conn, params=params)
        if not df.empty:
            df["timestamp"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
        return df

    def coverage(self) -> pd.DataFrame:
        sql = """
        SELECT source, symbol, timeframe,
               COUNT(*) AS bars,
               MIN(ts_ms) AS first_ts_ms,
               MAX(ts_ms) AS last_ts_ms
        FROM market_ohlcv
        GROUP BY source, symbol, timeframe
        ORDER BY source, symbol, timeframe
        """
        df = pd.read_sql_query(sql, self._conn)
        if not df.empty:
            df["first"] = pd.to_datetime(df["first_ts_ms"], unit="ms", utc=True)
            df["last"] = pd.to_datetime(df["last_ts_ms"], unit="ms", utc=True)
        return df

    def latest_ts_ms(self, source: str, symbol: str, timeframe: str) -> int | None:
        row = self._conn.execute(
            "SELECT MAX(ts_ms) FROM market_ohlcv WHERE source=? AND symbol=? AND timeframe=?",
            (source, symbol, timeframe),
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else None
