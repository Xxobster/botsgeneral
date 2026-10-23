"""LIVE-DATA-001 — exchange-server tip freshness + shared DATA_UNSAFE flag.

Canonical check (before every live decision / entry):

    expected_closed_open_ms = floor(server_now_ms / tf_ms) * tf_ms - tf_ms
    PASS iff local_closed_open_ms == expected_closed_open_ms
         and abs(local_wall_ms - server_now_ms) <= clock_skew_max_ms

Collector errors and tip-behind/ahead set shared SQLite ``meta`` keys that bots
read on heartbeat. Fail closed = no new entries; keep protective exits.
"""

from __future__ import annotations

import json
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from live_candles.models import TF_MS, normalize_symbol, normalize_timeframe
from live_candles.reader import newest_ts_ms, shared_db_path

# Conformance id (ops / readiness).
LIVE_DATA_001 = "LIVE-DATA-001"

META_PREFIX = "data_unsafe:"
DEFAULT_CLOCK_SKEW_MAX_MS = 5_000
DEFAULT_BINANCE_TIME_URL = "https://fapi.binance.com/fapi/v1/time"
DEFAULT_BYBIT_TIME_URL = "https://api.bybit.com/v5/market/time"


@dataclass(frozen=True)
class TipFreshnessResult:
    ok: bool
    code: str  # PASS | CANDLE_MISSING | CANDLE_STALE | CANDLE_AHEAD | CLOCK_SKEW | SERVER_TIME_FAIL
    exchange: str
    symbol: str
    timeframe: str
    local_tip_ms: int | None
    expected_tip_ms: int | None
    server_now_ms: int | None
    local_wall_ms: int
    clock_skew_ms: int | None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def expected_closed_open_ms(timeframe: str, *, server_now_ms: int) -> int:
    tf = normalize_timeframe(timeframe)
    tf_ms = int(TF_MS.get(tf) or 0)
    if tf_ms <= 0:
        raise ValueError(f"unknown timeframe {timeframe!r}")
    now = int(server_now_ms)
    return int((now // tf_ms) * tf_ms - tf_ms)


def clock_skew_max_ms_for(timeframe: str) -> int:
    tf = normalize_timeframe(timeframe)
    tf_ms = int(TF_MS.get(tf) or 0)
    if tf_ms <= 5 * 60_000:
        return 3_000
    return int(DEFAULT_CLOCK_SKEW_MAX_MS)


def clock_skew_excluding_rtt_ms(
    *,
    wall_before_ms: int,
    server_now_ms: int,
    wall_after_ms: int,
) -> int:
    """Clock skew that does not count HTTP round-trip as skew.

    If exchange server time sits inside ``[wall_before, wall_after]``, the
    difference is the request in flight — not a drifted machine clock.
    The 5 second (15-minute) / 3 second (1–5 minute) LIVE-DATA-001 cap still
    applies to the remaining gap outside that window.
    """
    lo = min(int(wall_before_ms), int(wall_after_ms))
    hi = max(int(wall_before_ms), int(wall_after_ms))
    server = int(server_now_ms)
    if lo <= server <= hi:
        return 0
    if server < lo:
        return lo - server
    return server - hi


def fetch_binance_server_time_ms(
    *, url: str = DEFAULT_BINANCE_TIME_URL, timeout_sec: float = 5.0
) -> int:
    """USDT-M futures server time (ms). Used for Binance signal tips."""
    req = urllib.request.Request(url, headers={"User-Agent": "live_candles-freshness/1"})
    with urllib.request.urlopen(req, timeout=float(timeout_sec)) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return int(payload["serverTime"])


def fetch_bybit_server_time_ms(
    *, url: str = DEFAULT_BYBIT_TIME_URL, timeout_sec: float = 5.0
) -> int:
    """Bybit server time (ms) — execution clock / signing skew checks."""
    req = urllib.request.Request(url, headers={"User-Agent": "live_candles-freshness/1"})
    with urllib.request.urlopen(req, timeout=float(timeout_sec)) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    # v5: result.timeNano is ns string; also timeSecond
    result = payload.get("result") or {}
    if "timeNano" in result and result["timeNano"] is not None:
        return int(int(result["timeNano"]) // 1_000_000)
    if "timeSecond" in result and result["timeSecond"] is not None:
        return int(result["timeSecond"]) * 1000
    # legacy fallback
    if "time" in payload:
        return int(payload["time"])
    raise KeyError("bybit time payload missing timeNano/timeSecond")


def fetch_server_time_ms(exchange: str, *, timeout_sec: float = 5.0) -> int:
    ex = str(exchange).lower().strip()
    if ex in {"binance", "binance_usdm", "binancef"}:
        return fetch_binance_server_time_ms(timeout_sec=timeout_sec)
    if ex in {"bybit", "bybit_linear"}:
        return fetch_bybit_server_time_ms(timeout_sec=timeout_sec)
    raise ValueError(f"no server-time endpoint for exchange={exchange!r}")


def evaluate_tip_freshness(
    *,
    exchange: str,
    symbol: str,
    timeframe: str,
    local_tip_ms: int | None,
    server_now_ms: int | None = None,
    local_wall_ms: int | None = None,
    clock_skew_max_ms: int | None = None,
    fetch_server_time: bool = True,
    timeout_sec: float = 5.0,
) -> TipFreshnessResult:
    """Compare local last closed open to exchange-server expected tip."""
    ex = str(exchange).lower().strip()
    sym = normalize_symbol(symbol)
    tf = normalize_timeframe(timeframe)
    wall_before = int(local_wall_ms if local_wall_ms is not None else time.time() * 1000)
    wall = wall_before
    skew_max = int(
        clock_skew_max_ms
        if clock_skew_max_ms is not None
        else clock_skew_max_ms_for(tf)
    )

    server = server_now_ms
    fetched_server = False
    if server is None and fetch_server_time:
        try:
            server = fetch_server_time_ms(ex, timeout_sec=timeout_sec)
            fetched_server = True
        except Exception as exc:  # noqa: BLE001
            return TipFreshnessResult(
                ok=False,
                code="SERVER_TIME_FAIL",
                exchange=ex,
                symbol=sym,
                timeframe=tf,
                local_tip_ms=int(local_tip_ms) if local_tip_ms is not None else None,
                expected_tip_ms=None,
                server_now_ms=None,
                local_wall_ms=wall_before,
                clock_skew_ms=None,
                detail=f"{type(exc).__name__}: {exc}",
            )
    if server is None:
        return TipFreshnessResult(
            ok=False,
            code="SERVER_TIME_FAIL",
            exchange=ex,
            symbol=sym,
            timeframe=tf,
            local_tip_ms=int(local_tip_ms) if local_tip_ms is not None else None,
            expected_tip_ms=None,
            server_now_ms=None,
            local_wall_ms=wall,
            clock_skew_ms=None,
            detail="server_now_ms missing",
        )

    server_i = int(server)
    if fetched_server and local_wall_ms is None:
        wall_after = int(time.time() * 1000)
        skew = clock_skew_excluding_rtt_ms(
            wall_before_ms=wall_before,
            server_now_ms=server_i,
            wall_after_ms=wall_after,
        )
        wall = wall_after
    else:
        skew = abs(wall - server_i)
    expected = expected_closed_open_ms(tf, server_now_ms=server_i)

    if local_tip_ms is None:
        return TipFreshnessResult(
            ok=False,
            code="CANDLE_MISSING",
            exchange=ex,
            symbol=sym,
            timeframe=tf,
            local_tip_ms=None,
            expected_tip_ms=expected,
            server_now_ms=server_i,
            local_wall_ms=wall,
            clock_skew_ms=skew,
            detail="no local closed tip",
        )
    tip = int(local_tip_ms)
    if skew > skew_max:
        return TipFreshnessResult(
            ok=False,
            code="CLOCK_SKEW",
            exchange=ex,
            symbol=sym,
            timeframe=tf,
            local_tip_ms=tip,
            expected_tip_ms=expected,
            server_now_ms=server_i,
            local_wall_ms=wall,
            clock_skew_ms=skew,
            detail=f"skew_ms={skew} > max={skew_max}",
        )
    if tip < expected:
        return TipFreshnessResult(
            ok=False,
            code="CANDLE_STALE",
            exchange=ex,
            symbol=sym,
            timeframe=tf,
            local_tip_ms=tip,
            expected_tip_ms=expected,
            server_now_ms=server_i,
            local_wall_ms=wall,
            clock_skew_ms=skew,
            detail="local tip behind exchange-server expected closed open",
        )
    if tip > expected:
        return TipFreshnessResult(
            ok=False,
            code="CANDLE_AHEAD",
            exchange=ex,
            symbol=sym,
            timeframe=tf,
            local_tip_ms=tip,
            expected_tip_ms=expected,
            server_now_ms=server_i,
            local_wall_ms=wall,
            clock_skew_ms=skew,
            detail="local tip ahead of exchange-server expected closed open",
        )
    return TipFreshnessResult(
        ok=True,
        code="PASS",
        exchange=ex,
        symbol=sym,
        timeframe=tf,
        local_tip_ms=tip,
        expected_tip_ms=expected,
        server_now_ms=server_i,
        local_wall_ms=wall,
        clock_skew_ms=skew,
        detail="",
    )


def data_unsafe_meta_key(exchange: str, symbol: str, timeframe: str) -> str:
    return (
        f"{META_PREFIX}{str(exchange).lower().strip()}:"
        f"{normalize_symbol(symbol)}:{normalize_timeframe(timeframe)}"
    )


def _connect_meta(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = shared_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=30)
    con.execute(
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    con.commit()
    return con


def write_data_unsafe(
    *,
    exchange: str,
    symbol: str,
    timeframe: str,
    reason: str,
    detail: dict[str, Any] | None = None,
    db_path: str | Path | None = None,
) -> str:
    """Persist DATA_UNSAFE for a series. Bots must refuse new entries while set."""
    key = data_unsafe_meta_key(exchange, symbol, timeframe)
    payload = {
        "ok": False,
        "reason": str(reason),
        "exchange": str(exchange).lower().strip(),
        "symbol": normalize_symbol(symbol),
        "timeframe": normalize_timeframe(timeframe),
        "updated_ms": int(time.time() * 1000),
        "conformance": LIVE_DATA_001,
        **(detail or {}),
    }
    con = _connect_meta(db_path)
    try:
        con.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(payload, separators=(",", ":"), default=str)),
        )
        con.commit()
    finally:
        con.close()
    return key


def clear_data_unsafe(
    *,
    exchange: str,
    symbol: str,
    timeframe: str,
    db_path: str | Path | None = None,
) -> None:
    key = data_unsafe_meta_key(exchange, symbol, timeframe)
    con = _connect_meta(db_path)
    try:
        con.execute("DELETE FROM meta WHERE key=?", (key,))
        con.commit()
    finally:
        con.close()


def read_data_unsafe(
    *,
    exchange: str,
    symbol: str,
    timeframe: str,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Return unsafe payload if set, else None (safe / unknown-absent)."""
    key = data_unsafe_meta_key(exchange, symbol, timeframe)
    path = shared_db_path(db_path)
    if not path.is_file():
        return None
    con = sqlite3.connect(str(path), timeout=30)
    try:
        row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    if not row or not row[0]:
        return None
    try:
        obj = json.loads(str(row[0]))
    except json.JSONDecodeError:
        return {"ok": False, "reason": "META_PARSE_FAIL", "raw": str(row[0])[:200]}
    if isinstance(obj, dict) and obj.get("ok") is False:
        return obj
    return None


def is_data_unsafe(
    *,
    exchange: str,
    symbol: str,
    timeframe: str,
    db_path: str | Path | None = None,
) -> bool:
    return read_data_unsafe(
        exchange=exchange, symbol=symbol, timeframe=timeframe, db_path=db_path
    ) is not None


def check_series_live_data_001(
    *,
    exchange: str,
    symbol: str,
    timeframe: str,
    local_tip_ms: int | None = None,
    db_path: str | Path | None = None,
    persist_flag: bool = True,
    server_now_ms: int | None = None,
    clock_skew_max_ms: int | None = None,
) -> TipFreshnessResult:
    """Full gate: tip vs server time + optional shared-flag persist.

    If ``local_tip_ms`` is None, reads newest tip from the shared candles DB.
    """
    tip = local_tip_ms
    if tip is None:
        tip = newest_ts_ms(exchange, symbol, timeframe, db_path=db_path)
    result = evaluate_tip_freshness(
        exchange=exchange,
        symbol=symbol,
        timeframe=timeframe,
        local_tip_ms=tip,
        server_now_ms=server_now_ms,
        clock_skew_max_ms=clock_skew_max_ms,
        fetch_server_time=server_now_ms is None,
    )
    if persist_flag:
        if result.ok:
            clear_data_unsafe(
                exchange=exchange, symbol=symbol, timeframe=timeframe, db_path=db_path
            )
        else:
            write_data_unsafe(
                exchange=exchange,
                symbol=symbol,
                timeframe=timeframe,
                reason=result.code,
                detail=result.to_dict(),
                db_path=db_path,
            )
    return result


def gate_allows_new_entries(
    *,
    exchange: str,
    symbol: str,
    timeframe: str,
    local_tip_ms: int | None = None,
    db_path: str | Path | None = None,
    persist_flag: bool = True,
    also_check_collector_flag: bool = True,
) -> tuple[bool, TipFreshnessResult, dict[str, Any] | None]:
    """Return (allow_entries, tip_result, existing_or_new_unsafe_payload).

    Protective exits must continue even when ``allow_entries`` is False.
    """
    if also_check_collector_flag:
        coll = read_data_unsafe(
            exchange=exchange,
            symbol="COLLECTOR",
            timeframe="1m",
            db_path=db_path,
        )
        if coll is not None:
            wall = int(time.time() * 1000)
            tip = local_tip_ms
            if tip is None:
                tip = newest_ts_ms(exchange, symbol, timeframe, db_path=db_path)
            tip_res = TipFreshnessResult(
                ok=False,
                code="COLLECTOR_ERROR",
                exchange=str(exchange).lower().strip(),
                symbol=normalize_symbol(symbol),
                timeframe=normalize_timeframe(timeframe),
                local_tip_ms=int(tip) if tip is not None else None,
                expected_tip_ms=None,
                server_now_ms=None,
                local_wall_ms=wall,
                clock_skew_ms=None,
                detail=str(coll.get("reason") or "COLLECTOR_ERROR"),
            )
            return False, tip_res, coll

    flagged = read_data_unsafe(
        exchange=exchange, symbol=symbol, timeframe=timeframe, db_path=db_path
    )
    tip_res = check_series_live_data_001(
        exchange=exchange,
        symbol=symbol,
        timeframe=timeframe,
        local_tip_ms=local_tip_ms,
        db_path=db_path,
        persist_flag=persist_flag,
    )
    if not tip_res.ok:
        return False, tip_res, read_data_unsafe(
            exchange=exchange, symbol=symbol, timeframe=timeframe, db_path=db_path
        ) or flagged
    return True, tip_res, None
