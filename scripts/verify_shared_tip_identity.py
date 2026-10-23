#!/usr/bin/env python3
"""Compare shared_candles closed tip OHLC vs live Binance Last REST (warehouse identity)."""
from __future__ import annotations

import sqlite3
import sys
import time

import pandas as pd

from market_data.fetch_binance import (
    TF_MS,
    drop_incomplete_bars,
    fetch_klines,
    tip_ohlc_fingerprint,
)


def main() -> int:
    db = sys.argv[1] if len(sys.argv) > 1 else "/var/lib/botsgeneral/shared_candles.db"
    pairs = []
    if len(sys.argv) > 2:
        for item in sys.argv[2].split(","):
            ex, sym, tf = item.split(":")
            pairs.append((ex, sym, tf))
    else:
        pairs = [
            ("binance", "BTCUSDT", "1h"),
            ("binance", "BTCUSDT", "4h"),
            ("binance", "BTCUSDT", "1w"),
            ("binance", "ETHUSDT", "1h"),
            ("binance", "ETHUSDT", "4h"),
            ("binance", "ETHUSDT", "1w"),
            ("binance", "SOLUSDT", "1h"),
            ("binance", "SOLUSDT", "4h"),
            ("binance", "SOLUSDT", "1w"),
        ]
    con = sqlite3.connect(db)
    bad = 0
    for ex, s, tf in pairs:
        if ex != "binance":
            continue
        rows = con.execute(
            """
            SELECT ts_ms, open, high, low, close, volume
            FROM candles
            WHERE exchange=? AND symbol=? AND timeframe=?
            ORDER BY ts_ms DESC LIMIT 5
            """,
            (ex, s, tf),
        ).fetchall()
        if not rows:
            print("EMPTY", s, tf)
            bad += 1
            continue
        df = pd.DataFrame(rows, columns=["ts_ms", "open", "high", "low", "close", "volume"])
        df = drop_incomplete_bars(df, tf)
        shared = tip_ohlc_fingerprint(df)
        start = int(time.time() * 1000) - TF_MS[tf] * 5
        live = tip_ohlc_fingerprint(
            fetch_klines(s, tf, price_type="last", start_ms=start)
        )
        ok = (
            shared
            and live
            and int(shared["ts_ms"]) == int(live["ts_ms"])
            and all(abs(float(shared[k]) - float(live[k])) < 1e-8 for k in ("open", "high", "low", "close"))
        )
        if not ok:
            bad += 1
        print(("OK" if ok else "BAD"), s, tf, "shared=", shared, "live=", live)
    meta = con.execute("SELECT key, value FROM meta").fetchall()
    print("meta", meta)
    print("bad", bad)
    con.close()
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
