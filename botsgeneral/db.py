from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Iterable

from botsgeneral.models import CandlePair, CandleRow, TF_MS

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
  exchange TEXT NOT NULL,
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  ts_ms INTEGER NOT NULL,
  open REAL NOT NULL,
  high REAL NOT NULL,
  low REAL NOT NULL,
  close REAL NOT NULL,
  volume REAL NOT NULL,
  quote_volume REAL,
  trades INTEGER,
  taker_buy_base REAL,
  taker_buy_quote REAL,
  updated_at_ms INTEGER NOT NULL,
  PRIMARY KEY (exchange, symbol, timeframe, ts_ms)
);
CREATE INDEX IF NOT EXISTS idx_candles_lookup
  ON candles (exchange, symbol, timeframe, ts_ms DESC);

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS discovered_pairs (
  exchange TEXT NOT NULL,
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  bot_name TEXT NOT NULL,
  updated_at_ms INTEGER NOT NULL,
  PRIMARY KEY (exchange, symbol, timeframe, bot_name)
);
"""


class CandleDB:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), timeout=60, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
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

    def upsert_candles(self, rows: Iterable[CandleRow]) -> int:
        now = int(time.time() * 1000)
        payload = [r.as_db_tuple(now) for r in rows]
        if not payload:
            return 0
        self._conn.executemany(
            """
            INSERT INTO candles (
              exchange, symbol, timeframe, ts_ms,
              open, high, low, close, volume,
              quote_volume, trades, taker_buy_base, taker_buy_quote,
              updated_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(exchange, symbol, timeframe, ts_ms) DO UPDATE SET
              open=excluded.open,
              high=excluded.high,
              low=excluded.low,
              close=excluded.close,
              volume=excluded.volume,
              quote_volume=excluded.quote_volume,
              trades=excluded.trades,
              taker_buy_base=excluded.taker_buy_base,
              taker_buy_quote=excluded.taker_buy_quote,
              updated_at_ms=excluded.updated_at_ms
            """,
            payload,
        )
        self._conn.commit()
        return len(payload)

    def replace_discovered(self, items: list[tuple[CandlePair, str]]) -> None:
        now = int(time.time() * 1000)
        self._conn.execute("DELETE FROM discovered_pairs")
        self._conn.executemany(
            """
            INSERT INTO discovered_pairs(exchange, symbol, timeframe, bot_name, updated_at_ms)
            VALUES (?, ?, ?, ?, ?)
            """,
            [(p.exchange, p.symbol, p.timeframe, bot, now) for p, bot in items],
        )
        self._conn.commit()
        self.set_meta("discovered_pairs_json", json.dumps([
            {"exchange": p.exchange, "symbol": p.symbol, "timeframe": p.timeframe, "bot": bot}
            for p, bot in items
        ]))

    def list_discovered(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT exchange, symbol, timeframe, bot_name, updated_at_ms FROM discovered_pairs "
            "ORDER BY exchange, symbol, timeframe, bot_name"
        ).fetchall()
        return [
            {
                "exchange": r[0],
                "symbol": r[1],
                "timeframe": r[2],
                "bot": r[3],
                "updated_at_ms": r[4],
            }
            for r in rows
        ]

    def latest_ts(self, pair: CandlePair) -> int | None:
        row = self._conn.execute(
            "SELECT MAX(ts_ms) FROM candles WHERE exchange=? AND symbol=? AND timeframe=?",
            (pair.exchange, pair.symbol, pair.timeframe),
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else None

    def candle_count(self, pair: CandlePair) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM candles WHERE exchange=? AND symbol=? AND timeframe=?",
            (pair.exchange, pair.symbol, pair.timeframe),
        ).fetchone()
        return int(row[0] if row else 0)

    def freshness_report(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT exchange, symbol, timeframe, MAX(ts_ms), COUNT(*)
            FROM candles
            GROUP BY exchange, symbol, timeframe
            ORDER BY exchange, symbol, timeframe
            """
        ).fetchall()
        now = int(time.time() * 1000)
        out = []
        for ex, sym, tf, last_ts, n in rows:
            lag_ms = now - int(last_ts) if last_ts else None
            expected = TF_MS.get(tf, 3_600_000)
            stale = lag_ms is not None and lag_ms > expected * 2.5
            out.append(
                {
                    "exchange": ex,
                    "symbol": sym,
                    "timeframe": tf,
                    "last_ts_ms": last_ts,
                    "bars": n,
                    "lag_sec": round(lag_ms / 1000, 1) if lag_ms is not None else None,
                    "stale": stale,
                }
            )
        return out
