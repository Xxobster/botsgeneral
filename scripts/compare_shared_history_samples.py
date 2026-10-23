#!/usr/bin/env python3
"""Sample OHLC identity: shared Binance series vs market_data Last (same as warehouse)."""
from __future__ import annotations

import sqlite3
import sys

from market_data.fetch_binance import TF_MS, drop_incomplete_bars, fetch_klines
import time


def _compare_pair(con: sqlite3.Connection, symbol: str, timeframe: str) -> dict:
    rows = con.execute(
        """
        SELECT ts_ms, open, high, low, close
        FROM candles
        WHERE exchange='binance' AND symbol=? AND timeframe=?
        ORDER BY ts_ms
        """,
        (symbol, timeframe),
    ).fetchall()
    if not rows:
        return {"symbol": symbol, "timeframe": timeframe, "ok": False, "reason": "empty shared"}
    step = TF_MS.get(timeframe, 0)
    now = int(time.time() * 1000)
    # Only compare closed bars (ignore any stale forming tip leftover)
    rows = [r for r in rows if int(r[0]) + int(step) <= now]
    if not rows:
        return {"symbol": symbol, "timeframe": timeframe, "ok": False, "reason": "no closed bars"}
    n = len(rows)
    idxs = sorted({0, n // 2, n - 1, max(0, n - 50), max(0, n - 500)})
    sample_ts = [int(rows[i][0]) for i in idxs]
    shared = {int(r[0]): (float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in rows}
    start = min(sample_ts) - 1
    end = max(sample_ts) + 1
    # For mid/history identity fetch only a window around samples is expensive if sparse;
    # fetch tip window + early window separately.
    live_map: dict[int, tuple] = {}
    early = fetch_klines(
        symbol,
        timeframe,
        price_type="last",
        start_ms=int(rows[0][0]),
        end_ms=int(rows[min(2000, n - 1)][0]),
        drop_incomplete=False,
        drop_junk=True,
    )
    tip = fetch_klines(
        symbol,
        timeframe,
        price_type="last",
        start_ms=int(rows[max(0, n - 2000)][0]),
        drop_incomplete=True,
        drop_junk=True,
    )
    for df in (early, tip):
        if df is None or df.empty:
            continue
        for _, r in df.iterrows():
            live_map[int(r["ts_ms"])] = (
                float(r["open"]),
                float(r["high"]),
                float(r["low"]),
                float(r["close"]),
            )
    mismatches = []
    checked = 0
    for ts in sample_ts:
        if ts not in live_map:
            # forming tip may be dropped from live
            continue
        checked += 1
        if shared[ts] != live_map[ts]:
            mismatches.append({"ts_ms": ts, "shared": shared[ts], "live": live_map[ts]})
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "shared_bars": n,
        "checked": checked,
        "ok": checked > 0 and not mismatches,
        "mismatches": mismatches[:5],
    }


def main() -> int:
    db = sys.argv[1] if len(sys.argv) > 1 else "/var/lib/botsgeneral/shared_candles.db"
    pairs = [
        ("BTCUSDT", "1h"),
        ("BTCUSDT", "4h"),
        ("BTCUSDT", "1w"),
        ("ETHUSDT", "1h"),
        ("ETHUSDT", "4h"),
        ("ETHUSDT", "1w"),
        ("SOLUSDT", "1h"),
        ("SOLUSDT", "4h"),
        ("SOLUSDT", "1w"),
    ]
    if len(sys.argv) > 2:
        pairs = []
        for item in sys.argv[2].split(","):
            s, tf = item.split(":")
            pairs.append((s, tf))
    con = sqlite3.connect(db)
    bad = 0
    for s, tf in pairs:
        # skip missing series quietly
        n = con.execute(
            "SELECT COUNT(*) FROM candles WHERE exchange='binance' AND symbol=? AND timeframe=?",
            (s, tf),
        ).fetchone()[0]
        if not n:
            print("SKIP", s, tf, "not in shared")
            continue
        r = _compare_pair(con, s, tf)
        if not r["ok"]:
            bad += 1
        print(("OK" if r["ok"] else "BAD"), r)
    con.close()
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
