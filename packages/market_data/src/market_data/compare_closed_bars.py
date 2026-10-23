"""Closed-bar OHLC identity gate: shared_candles.db tip vs market_ohlcv tip."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from market_data.fetch_binance import TF_MS, drop_incomplete_bars, tip_ohlc_fingerprint
from market_data.paths import market_ohlcv_db


def _load_shared_tip(
    db_path: Path,
    *,
    exchange: str,
    symbol: str,
    timeframe: str,
) -> dict | None:
    con = sqlite3.connect(str(db_path))
    row = con.execute(
        """
        SELECT ts_ms, open, high, low, close, volume
        FROM candles
        WHERE exchange=? AND symbol=? AND timeframe=?
        ORDER BY ts_ms DESC
        LIMIT 5
        """,
        (exchange, symbol.upper(), timeframe),
    ).fetchall()
    con.close()
    if not row:
        return None
    import pandas as pd

    df = pd.DataFrame(row, columns=["ts_ms", "open", "high", "low", "close", "volume"])
    df = drop_incomplete_bars(df, timeframe)
    return tip_ohlc_fingerprint(df)


def _load_warehouse_tip(
    db_path: Path,
    *,
    symbol: str,
    timeframe: str,
    source: str = "binance",
) -> dict | None:
    con = sqlite3.connect(str(db_path))
    row = con.execute(
        """
        SELECT ts_ms, open, high, low, close, volume
        FROM market_ohlcv
        WHERE source=? AND symbol=? AND timeframe=?
        ORDER BY ts_ms DESC
        LIMIT 5
        """,
        (source, symbol.upper(), timeframe),
    ).fetchall()
    con.close()
    if not row:
        return None
    import pandas as pd

    df = pd.DataFrame(row, columns=["ts_ms", "open", "high", "low", "close", "volume"])
    df = drop_incomplete_bars(df, timeframe)
    return tip_ohlc_fingerprint(df)


def compare_tip(
    *,
    symbol: str,
    timeframe: str,
    shared_db: Path,
    warehouse_db: Path,
    exchange: str = "binance",
    source: str = "binance",
    tol: float = 1e-8,
) -> dict:
    shared = _load_shared_tip(
        shared_db, exchange=exchange, symbol=symbol, timeframe=timeframe
    )
    wh = _load_warehouse_tip(
        warehouse_db, symbol=symbol, timeframe=timeframe, source=source
    )
    out: dict = {
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "shared": shared,
        "warehouse": wh,
        "ok": False,
        "reason": "",
    }
    if shared is None or wh is None:
        out["reason"] = "missing tip on one or both stores"
        return out
    if int(shared["ts_ms"]) != int(wh["ts_ms"]):
        out["reason"] = f"ts_ms mismatch shared={shared['ts_ms']} warehouse={wh['ts_ms']}"
        return out
    for k in ("open", "high", "low", "close"):
        if abs(float(shared[k]) - float(wh[k])) > tol:
            out["reason"] = f"{k} mismatch shared={shared[k]} warehouse={wh[k]}"
            return out
    out["ok"] = True
    out["reason"] = "closed-bar OHLC identity"
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Compare shared vs warehouse closed-bar tip OHLC")
    p.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT")
    p.add_argument("--timeframes", default="1h,4h,1w")
    p.add_argument(
        "--shared-db",
        default="",
        help="Path to shared_candles.db (default: env SHARED_CANDLES_DB or local data/)",
    )
    p.add_argument("--warehouse-db", default="", help="Path to market_ohlcv.sqlite")
    args = p.parse_args(argv)

    import os

    shared = Path(
        args.shared_db
        or os.environ.get("SHARED_CANDLES_DB")
        or Path("data") / "shared_candles.db"
    )
    warehouse = Path(args.warehouse_db or market_ohlcv_db())
    symbols = [x.strip().upper() for x in args.symbols.split(",") if x.strip()]
    tfs = [x.strip().lower() for x in args.timeframes.split(",") if x.strip()]
    results = []
    bad = 0
    for s in symbols:
        for tf in tfs:
            if tf not in TF_MS and tf != "1w":
                continue
            r = compare_tip(
                symbol=s,
                timeframe=tf,
                shared_db=shared,
                warehouse_db=warehouse,
            )
            results.append(r)
            if not r["ok"]:
                bad += 1
    print(json.dumps({"shared_db": str(shared), "warehouse_db": str(warehouse), "results": results}, indent=2))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
