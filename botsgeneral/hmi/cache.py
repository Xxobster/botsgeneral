"""Incremental Bybit closed-PnL cache (SQLite). Avoids re-fetching full history."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable

# Re-fetch a short overlap so in-flight closes are not missed.
_OVERLAP_MS = 2 * 60 * 60 * 1000

FetchFn = Callable[[int, int], list[dict[str, Any]]]


def default_cache_path() -> Path | None:
    env = os.environ.get("BOTSGENERAL_PNL_CACHE")
    if env in ("0", "off", "false", "no"):
        return None
    if env:
        return Path(env)
    linux = Path("/var/lib/botsgeneral")
    if linux.is_dir():
        return linux / "hmi_cache.sqlite"
    return None


def trade_dedupe_key(t: dict[str, Any]) -> str:
    return (
        str(t.get("orderId") or "")
        + "|"
        + str(t.get("updatedTime") or "")
        + "|"
        + str(t.get("symbol") or "")
        + "|"
        + str(t.get("closedPnl") or "")
        + "|"
        + str(t.get("qty") or "")
    )


def _trade_ts_ms(t: dict[str, Any]) -> int:
    try:
        return int(t.get("updatedTime") or t.get("createdTime") or 0)
    except (TypeError, ValueError):
        return 0


class ClosedPnlCache:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS closed_pnl (
              account TEXT NOT NULL,
              dedupe_key TEXT NOT NULL,
              symbol TEXT,
              updated_time_ms INTEGER,
              payload_json TEXT NOT NULL,
              PRIMARY KEY (account, dedupe_key)
            );
            CREATE INDEX IF NOT EXISTS idx_closed_acct_ts
              ON closed_pnl(account, updated_time_ms);
            CREATE TABLE IF NOT EXISTS cache_meta (
              account TEXT PRIMARY KEY,
              covered_from_ms INTEGER,
              last_end_ms INTEGER,
              updated_at_ms INTEGER
            );
            """
        )
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _meta(self, account: str) -> tuple[int | None, int | None]:
        row = self._conn.execute(
            "SELECT covered_from_ms, last_end_ms FROM cache_meta WHERE account=?",
            (account,),
        ).fetchone()
        if not row:
            return None, None
        return int(row[0]) if row[0] is not None else None, int(row[1]) if row[1] is not None else None

    def _upsert_rows(self, account: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        payload = [
            (
                account,
                trade_dedupe_key(t),
                str(t.get("symbol") or "").upper(),
                _trade_ts_ms(t),
                json.dumps(t, separators=(",", ":"), default=str),
            )
            for t in rows
        ]
        self._conn.executemany(
            """
            INSERT INTO closed_pnl(account, dedupe_key, symbol, updated_time_ms, payload_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(account, dedupe_key) DO UPDATE SET
              symbol=excluded.symbol,
              updated_time_ms=excluded.updated_time_ms,
              payload_json=excluded.payload_json
            """,
            payload,
        )

    def _set_meta(self, account: str, covered_from_ms: int, last_end_ms: int) -> None:
        self._conn.execute(
            """
            INSERT INTO cache_meta(account, covered_from_ms, last_end_ms, updated_at_ms)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(account) DO UPDATE SET
              covered_from_ms=MIN(cache_meta.covered_from_ms, excluded.covered_from_ms),
              last_end_ms=MAX(cache_meta.last_end_ms, excluded.last_end_ms),
              updated_at_ms=excluded.updated_at_ms
            """,
            (account, int(covered_from_ms), int(last_end_ms), int(time.time() * 1000)),
        )

    def load_since(self, account: str, start_ms: int, symbol: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if symbol:
                rows = self._conn.execute(
                    """
                    SELECT payload_json FROM closed_pnl
                    WHERE account=? AND updated_time_ms>=? AND symbol=?
                    ORDER BY updated_time_ms ASC
                    """,
                    (account, int(start_ms), str(symbol).upper()),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT payload_json FROM closed_pnl
                    WHERE account=? AND updated_time_ms>=?
                    ORDER BY updated_time_ms ASC
                    """,
                    (account, int(start_ms)),
                ).fetchall()
        out: list[dict[str, Any]] = []
        for (raw,) in rows:
            try:
                out.append(json.loads(raw))
            except (TypeError, json.JSONDecodeError):
                continue
        return out

    def get_or_fetch(
        self,
        account: str,
        start_ms: int,
        fetch_fn: FetchFn,
        symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return closed rows >= start_ms, fetching only uncovered windows."""
        start_ms = int(start_ms)
        now_ms = int(time.time() * 1000)
        with self._lock:
            covered_from, last_end = self._meta(account)
        windows: list[tuple[int, int]] = []
        if covered_from is None or last_end is None:
            windows.append((start_ms, now_ms))
        else:
            if start_ms < covered_from:
                windows.append((start_ms, covered_from))
            fetch_from = max(start_ms, int(last_end) - _OVERLAP_MS)
            if now_ms > fetch_from:
                windows.append((fetch_from, now_ms))
        for a, b in windows:
            if b <= a:
                continue
            rows = fetch_fn(int(a), int(b)) or []
            with self._lock:
                self._upsert_rows(account, rows)
                self._set_meta(account, a, b)
                self._conn.commit()
        return self.load_since(account, start_ms, symbol=symbol)


_CACHE: ClosedPnlCache | None = None
_CACHE_LOCK = threading.Lock()


def closed_pnl_cache() -> ClosedPnlCache | None:
    global _CACHE
    path = default_cache_path()
    if path is None:
        return None
    with _CACHE_LOCK:
        if _CACHE is None or _CACHE.path != path:
            _CACHE = ClosedPnlCache(path)
        return _CACHE
