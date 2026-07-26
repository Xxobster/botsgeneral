"""Detect and repair Binance USDⓈ-M 1m Mark Price gaps."""

from __future__ import annotations

import argparse
import sqlite3

import numpy as np
import pandas as pd

from botsgeneral.research_candles.db import DEFAULT_DB_PATH, ResearchCandleDB
from botsgeneral.research_candles.fetch_binance import fetch_klines

TF_MS = 60_000


def gap_ranges(path: str, symbol: str) -> np.ndarray:
    uri = f"file:{path}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=120) as conn:
        rows = conn.execute(
            """
            SELECT ts_ms
            FROM market_ohlcv
            WHERE source='binance_mark' AND symbol=? AND timeframe='1m'
            ORDER BY ts_ms
            """,
            (symbol,),
        ).fetchall()
    ts = np.fromiter((row[0] for row in rows), dtype=np.int64, count=len(rows))
    if ts.size < 2:
        return np.empty((0, 3), dtype=np.int64)
    delta = np.diff(ts)
    idx = np.flatnonzero(delta > TF_MS)
    if idx.size == 0:
        return np.empty((0, 3), dtype=np.int64)
    starts = ts[idx] + TF_MS
    ends = ts[idx + 1] - TF_MS
    missing = ((ends - starts) // TF_MS) + 1
    return np.column_stack((starts, ends, missing))


def repair(path: str, symbols: tuple[str, ...]) -> None:
    db = ResearchCandleDB(path)
    try:
        for symbol in symbols:
            gaps = gap_ranges(path, symbol)
            print(f"{symbol}: {len(gaps)} gaps, {int(gaps[:, 2].sum()) if gaps.size else 0} missing minutes")
            # Requests are inherently sequential; gap detection/counting above is vectorized.
            for start_ms, end_ms, expected in gaps:
                df = fetch_klines(
                    symbol,
                    "1m",
                    market="binance",
                    price_type="mark",
                    start_ms=int(start_ms),
                    end_ms=int(end_ms),
                    sleep_s=0.02,
                )
                if df.empty:
                    print(
                        f"WARN {symbol}: endpoint returned no rows for "
                        f"{pd.to_datetime(start_ms, unit='ms', utc=True)}.."
                        f"{pd.to_datetime(end_ms, unit='ms', utc=True)} ({expected} expected)"
                    )
                    continue
                db.upsert_df(
                    df,
                    source="binance_mark",
                    symbol=symbol,
                    timeframe="1m",
                    price_type="mark_price",
                    product="USDⓈ-M",
                    source_endpoint="/fapi/v1/markPriceKlines",
                )
                print(f"{symbol}: repaired {len(df)}/{expected} minutes")
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    symbols = tuple(s.strip().upper() for s in args.symbols.split(",") if s.strip())
    if args.dry_run:
        for symbol in symbols:
            gaps = gap_ranges(args.db, symbol)
            print(gaps)
        return 0
    repair(args.db, symbols)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
