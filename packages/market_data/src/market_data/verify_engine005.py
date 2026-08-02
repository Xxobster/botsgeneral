"""Read-only ENGINE-005 contract verification for Binance USDⓈ-M Mark Price."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from market_data.db import DEFAULT_DB_PATH

EXPECTED_PRICE_TYPE = "mark_price"
EXPECTED_PRODUCT = "USDⓈ-M"
EXPECTED_ENDPOINT = "/fapi/v1/markPriceKlines"


def verify(path: str | Path = DEFAULT_DB_PATH) -> list[dict]:
    uri = f"file:{Path(path).resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=120) as conn:
        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(market_ohlcv)").fetchall()
        }
        required = {"price_type", "product", "source_endpoint"}
        missing = required - columns
        if missing:
            raise RuntimeError(f"Missing provenance columns: {sorted(missing)}")

        rows = conn.execute(
            """
            SELECT symbol, COUNT(*) AS bars, MIN(ts_ms), MAX(ts_ms),
                   CAST((MAX(ts_ms) - MIN(ts_ms)) / 60000 AS INTEGER)
                       + 1 - COUNT(*) AS missing_minutes,
                   COUNT(DISTINCT price_type),
                   COUNT(DISTINCT product),
                   COUNT(DISTINCT source_endpoint)
            FROM market_ohlcv
            WHERE source='binance_mark'
              AND timeframe='1m'
              AND symbol IN ('BTCUSDT', 'ETHUSDT')
              AND price_type=?
              AND product=?
              AND source_endpoint=?
            GROUP BY symbol
            ORDER BY symbol
            """,
            (EXPECTED_PRICE_TYPE, EXPECTED_PRODUCT, EXPECTED_ENDPOINT),
        ).fetchall()

        invalid = conn.execute(
            """
            SELECT COUNT(*)
            FROM market_ohlcv
            WHERE source='binance_mark'
              AND (
                price_type IS NOT ?
                OR product IS NOT ?
                OR source_endpoint IS NOT ?
              )
            """,
            (EXPECTED_PRICE_TYPE, EXPECTED_PRODUCT, EXPECTED_ENDPOINT),
        ).fetchone()[0]

    result = [
        {
            "symbol": row[0],
            "bars": int(row[1]),
            "first_ts_ms": int(row[2]),
            "last_ts_ms": int(row[3]),
            "missing_minutes": int(row[4]),
            "price_type": EXPECTED_PRICE_TYPE,
            "product": EXPECTED_PRODUCT,
            "source_endpoint": EXPECTED_ENDPOINT,
        }
        for row in rows
    ]
    if {row["symbol"] for row in result} != {"BTCUSDT", "ETHUSDT"}:
        raise RuntimeError("BTCUSDT/ETHUSDT 1m Mark Price series not both present")
    if invalid:
        raise RuntimeError(f"{invalid} binance_mark rows have invalid provenance")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    args = parser.parse_args()
    for row in verify(args.db):
        print(json.dumps(row, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
