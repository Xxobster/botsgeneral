"""SQLite cache of Bybit instrument limits used by research sizing."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Sequence

from ..contracts import InstrumentSpec
from .bybit import BybitInstrument, fetch_instrument, fetch_instruments

DEFAULT_CACHE = Path(r"D:\projectsdata\candles\bybit_instruments.sqlite")

SCHEMA = """
CREATE TABLE IF NOT EXISTS instruments (
    symbol TEXT PRIMARY KEY,
    tick_size REAL NOT NULL,
    qty_step REAL NOT NULL,
    min_qty REAL NOT NULL,
    min_notional REAL NOT NULL,
    max_qty REAL NOT NULL,
    max_leverage REAL NOT NULL,
    status TEXT,
    retrieved_at_ms INTEGER NOT NULL
);
"""


class InstrumentCache:
    def __init__(self, path: str | Path = DEFAULT_CACHE) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        return conn

    def upsert(self, items: Sequence[BybitInstrument]) -> None:
        with self._conn() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO instruments (
                    symbol, tick_size, qty_step, min_qty, min_notional,
                    max_qty, max_leverage, status, retrieved_at_ms
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                [
                    (
                        i.symbol,
                        i.tick_size,
                        i.qty_step,
                        i.min_qty,
                        i.min_notional,
                        i.max_qty,
                        i.max_leverage,
                        i.status,
                        i.retrieved_at_ms,
                    )
                    for i in items
                ],
            )

    def get(self, symbol: str) -> BybitInstrument | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM instruments WHERE symbol = ?", (symbol.upper(),)
            ).fetchone()
        if row is None:
            return None
        return BybitInstrument(**dict(row))

    def all(self) -> list[BybitInstrument]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM instruments ORDER BY symbol"
            ).fetchall()
        return [BybitInstrument(**dict(r)) for r in rows]

    def refresh(
        self,
        symbols: Sequence[str] | None = None,
        *,
        use_auth: bool = True,
    ) -> list[BybitInstrument]:
        items = fetch_instruments(symbols, use_auth=use_auth)
        self.upsert(items)
        return items

    def instrument_spec(
        self,
        symbol: str,
        *,
        refresh_if_missing: bool = True,
        max_age_ms: int = 7 * 86_400_000,
    ) -> InstrumentSpec:
        """Return a tradesim ``InstrumentSpec`` for ``symbol``.

        Refreshes from Bybit when missing or older than ``max_age_ms`` (default 7 days).
        """
        row = self.get(symbol)
        now = int(time.time() * 1000)
        stale = row is None or (now - row.retrieved_at_ms) > max_age_ms
        if stale and refresh_if_missing:
            fetched = fetch_instrument(symbol, use_auth=True)
            self.upsert([fetched])
            row = fetched
        if row is None:
            raise KeyError(
                f"no Bybit instrument cache for {symbol!r}; "
                "run: python -m tradesim.venue refresh --symbols SYMBOL"
            )
        return row.to_instrument_spec()
