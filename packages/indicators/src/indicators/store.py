"""SQLite warehouse for shared indicators (programs open and copy from here)."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Iterable

import pandas as pd

from .compute import StructureBundle, tables_from_bundle
from .paths import indicators_db

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS series (
  source TEXT NOT NULL,
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  swing_left INTEGER NOT NULL,
  swing_right INTEGER NOT NULL,
  n_bars INTEGER NOT NULL,
  n_swings INTEGER NOT NULL,
  first_ts_ms INTEGER,
  last_ts_ms INTEGER,
  computed_at_ms INTEGER NOT NULL,
  params_json TEXT NOT NULL,
  PRIMARY KEY (source, symbol, timeframe, swing_left, swing_right)
);

CREATE TABLE IF NOT EXISTS swings (
  source TEXT NOT NULL,
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  swing_left INTEGER NOT NULL,
  swing_right INTEGER NOT NULL,
  swing_id INTEGER NOT NULL,
  kind TEXT NOT NULL,
  pivot_i INTEGER NOT NULL,
  confirm_i INTEGER NOT NULL,
  pivot_ts_ms INTEGER NOT NULL,
  confirm_ts_ms INTEGER NOT NULL,
  price REAL NOT NULL,
  PRIMARY KEY (source, symbol, timeframe, swing_left, swing_right, swing_id)
);

CREATE TABLE IF NOT EXISTS structure_events (
  source TEXT NOT NULL,
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  swing_left INTEGER NOT NULL,
  swing_right INTEGER NOT NULL,
  event_id INTEGER NOT NULL,
  label TEXT NOT NULL,
  swing_id INTEGER NOT NULL,
  prev_swing_id INTEGER,
  ts_ms INTEGER NOT NULL,
  pivot_ts_ms INTEGER NOT NULL,
  price REAL NOT NULL,
  PRIMARY KEY (source, symbol, timeframe, swing_left, swing_right, event_id)
);

CREATE TABLE IF NOT EXISTS legs (
  source TEXT NOT NULL,
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  swing_left INTEGER NOT NULL,
  swing_right INTEGER NOT NULL,
  leg_id INTEGER NOT NULL,
  direction TEXT NOT NULL,
  start_swing_id INTEGER NOT NULL,
  end_swing_id INTEGER NOT NULL,
  start_ts_ms INTEGER NOT NULL,
  end_ts_ms INTEGER NOT NULL,
  start_price REAL NOT NULL,
  end_price REAL NOT NULL,
  length_abs REAL NOT NULL,
  length_pct REAL NOT NULL,
  kind TEXT NOT NULL,
  retrace_pct REAL,
  fib_ratio REAL,
  fib_label TEXT,
  PRIMARY KEY (source, symbol, timeframe, swing_left, swing_right, leg_id)
);

CREATE TABLE IF NOT EXISTS levels (
  source TEXT NOT NULL,
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  swing_left INTEGER NOT NULL,
  swing_right INTEGER NOT NULL,
  level_id INTEGER NOT NULL,
  kind TEXT NOT NULL,
  price REAL NOT NULL,
  origin_swing_id INTEGER NOT NULL,
  origin_ts_ms INTEGER NOT NULL,
  confirm_ts_ms INTEGER NOT NULL,
  PRIMARY KEY (source, symbol, timeframe, swing_left, swing_right, level_id)
);

CREATE TABLE IF NOT EXISTS bar_features (
  source TEXT NOT NULL,
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  swing_left INTEGER NOT NULL,
  swing_right INTEGER NOT NULL,
  ts_ms INTEGER NOT NULL,
  close REAL,
  last_sh_price REAL,
  last_sh_ts_ms REAL,
  dist_last_sh_pct REAL,
  last_sl_price REAL,
  last_sl_ts_ms REAL,
  dist_last_sl_pct REAL,
  structure_bias INTEGER,
  last_structure_label TEXT,
  last_leg_dir TEXT,
  last_leg_kind TEXT,
  last_leg_len_pct REAL,
  last_retrace_pct REAL,
  last_retrace_fib TEXT,
  fib_0000 REAL,
  fib_0236 REAL,
  fib_0382 REAL,
  fib_0500 REAL,
  fib_0618 REAL,
  fib_0786 REAL,
  fib_1000 REAL,
  fib_1272 REAL,
  fib_1618 REAL,
  fib_2000 REAL,
  fib_2618 REAL,
  dist_fib_0236_pct REAL,
  dist_fib_0382_pct REAL,
  dist_fib_0500_pct REAL,
  dist_fib_0618_pct REAL,
  dist_fib_0786_pct REAL,
  nearest_support REAL,
  nearest_resistance REAL,
  dist_support_pct REAL,
  dist_resistance_pct REAL,
  PRIMARY KEY (source, symbol, timeframe, swing_left, swing_right, ts_ms)
);

CREATE INDEX IF NOT EXISTS idx_bar_lookup
  ON bar_features(symbol, timeframe, ts_ms);
CREATE INDEX IF NOT EXISTS idx_swings_lookup
  ON swings(symbol, timeframe, confirm_ts_ms);
CREATE INDEX IF NOT EXISTS idx_levels_lookup
  ON levels(symbol, timeframe, kind, price);
"""


class IndicatorDB:
    """Authoritative shared indicators SQLite store."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else indicators_db()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), timeout=120, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA temp_store=MEMORY")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "IndicatorDB":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

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

    def coverage(self) -> pd.DataFrame:
        return pd.read_sql_query(
            """
            SELECT source, symbol, timeframe, swing_left, swing_right,
                   n_bars, n_swings, first_ts_ms, last_ts_ms, computed_at_ms
            FROM series
            ORDER BY source, symbol, timeframe
            """,
            self._conn,
        )

    def delete_series(
        self,
        *,
        source: str,
        symbol: str,
        timeframe: str,
        swing_left: int,
        swing_right: int,
    ) -> None:
        keys = (source, symbol, timeframe, swing_left, swing_right)
        for table in ("bar_features", "levels", "legs", "structure_events", "swings", "series"):
            self._conn.execute(
                f"DELETE FROM {table} WHERE source=? AND symbol=? AND timeframe=? "
                f"AND swing_left=? AND swing_right=?",
                keys,
            )
        self._conn.commit()

    def upsert_bundle(self, bundle: StructureBundle) -> dict[str, int]:
        """Replace all tables for this series key with a freshly computed bundle."""
        src, sym, tf = bundle.source, bundle.symbol, bundle.timeframe
        left, right = bundle.swing_left, bundle.swing_right
        self.delete_series(
            source=src, symbol=sym, timeframe=tf, swing_left=left, swing_right=right
        )
        tables = tables_from_bundle(bundle)
        counts: dict[str, int] = {}
        for name, df in tables.items():
            counts[name] = self._insert_keyed(df, name, src, sym, tf, left, right)

        first_ts = int(bundle.ohlcv["ts_ms"].iloc[0]) if bundle.n_bars else None
        last_ts = int(bundle.ohlcv["ts_ms"].iloc[-1]) if bundle.n_bars else None
        params = {
            "swing_left": left,
            "swing_right": right,
            "fib": "0/0.236/0.382/0.5/0.618/0.786/1/1.272/1.618/2/2.618",
        }
        self._conn.execute(
            """
            INSERT INTO series(
              source, symbol, timeframe, swing_left, swing_right,
              n_bars, n_swings, first_ts_ms, last_ts_ms, computed_at_ms, params_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                src,
                sym,
                tf,
                left,
                right,
                bundle.n_bars,
                bundle.n_swings,
                first_ts,
                last_ts,
                int(time.time() * 1000),
                json.dumps(params, sort_keys=True),
            ),
        )
        self._conn.commit()
        counts["series"] = 1
        return counts

    def _insert_keyed(
        self,
        df: pd.DataFrame,
        table: str,
        source: str,
        symbol: str,
        timeframe: str,
        swing_left: int,
        swing_right: int,
    ) -> int:
        if df is None or df.empty:
            return 0
        data = df.copy()
        data.insert(0, "swing_right", swing_right)
        data.insert(0, "swing_left", swing_left)
        data.insert(0, "timeframe", timeframe)
        data.insert(0, "symbol", symbol)
        data.insert(0, "source", source)
        # Align to table columns (ignore extras).
        cols = [r[1] for r in self._conn.execute(f"PRAGMA table_info({table})").fetchall()]
        for c in cols:
            if c not in data.columns:
                data[c] = None
        data = data[cols]
        # Faster than per-row Python float checks on large frames.
        records = data.astype(object).where(pd.notna(data), None).to_numpy().tolist()
        placeholders = ",".join(["?"] * len(cols))
        col_sql = ",".join(cols)
        sql = f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders})"
        chunk = 5_000
        for i in range(0, len(records), chunk):
            self._conn.executemany(sql, records[i : i + chunk])
        return len(records)

    def load_bar_features(
        self,
        symbol: str,
        timeframe: str,
        *,
        source: str | None = None,
        swing_left: int = 2,
        swing_right: int = 2,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> pd.DataFrame:
        clauses = ["symbol=?", "timeframe=?", "swing_left=?", "swing_right=?"]
        params: list = [symbol, timeframe, swing_left, swing_right]
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
        return pd.read_sql_query(
            f"SELECT * FROM bar_features WHERE {where} ORDER BY ts_ms",
            self._conn,
            params=params,
        )

    def load_swings(
        self,
        symbol: str,
        timeframe: str,
        *,
        source: str | None = None,
        swing_left: int = 2,
        swing_right: int = 2,
    ) -> pd.DataFrame:
        return self._load_table(
            "swings", symbol, timeframe, source=source, swing_left=swing_left, swing_right=swing_right
        )

    def load_legs(
        self,
        symbol: str,
        timeframe: str,
        *,
        source: str | None = None,
        swing_left: int = 2,
        swing_right: int = 2,
    ) -> pd.DataFrame:
        return self._load_table(
            "legs", symbol, timeframe, source=source, swing_left=swing_left, swing_right=swing_right
        )

    def load_levels(
        self,
        symbol: str,
        timeframe: str,
        *,
        source: str | None = None,
        swing_left: int = 2,
        swing_right: int = 2,
    ) -> pd.DataFrame:
        return self._load_table(
            "levels", symbol, timeframe, source=source, swing_left=swing_left, swing_right=swing_right
        )

    def load_structure_events(
        self,
        symbol: str,
        timeframe: str,
        *,
        source: str | None = None,
        swing_left: int = 2,
        swing_right: int = 2,
    ) -> pd.DataFrame:
        return self._load_table(
            "structure_events",
            symbol,
            timeframe,
            source=source,
            swing_left=swing_left,
            swing_right=swing_right,
        )

    def _load_table(
        self,
        table: str,
        symbol: str,
        timeframe: str,
        *,
        source: str | None,
        swing_left: int,
        swing_right: int,
    ) -> pd.DataFrame:
        clauses = ["symbol=?", "timeframe=?", "swing_left=?", "swing_right=?"]
        params: list = [symbol, timeframe, swing_left, swing_right]
        if source:
            clauses.append("source=?")
            params.append(source)
        where = " AND ".join(clauses)
        return pd.read_sql_query(
            f"SELECT * FROM {table} WHERE {where} ORDER BY rowid",
            self._conn,
            params=params,
        )
