"""Command-line interface for the shared leakage engine."""

from __future__ import annotations

import argparse
import importlib
import sqlite3
import sys
from pathlib import Path

import pandas as pd

from .engine import format_report, run_leakage_audit
from .ensure_source import prefer_botsgeneral_leakage


def _load_builder(spec: str):
    """Load ``module.path:callable`` feature builder."""
    if ":" not in spec:
        raise SystemExit(
            "--builder must be 'module.path:callable' "
            "(e.g. utils.calc_indicators:build_features_for_guard)"
        )
    mod_name, attr = spec.split(":", 1)
    mod = importlib.import_module(mod_name)
    fn = getattr(mod, attr, None)
    if fn is None or not callable(fn):
        raise SystemExit(f"builder not found / not callable: {spec}")
    return fn


def _load_ohlcv(
    db: Path,
    symbol: str,
    timeframe: str,
    *,
    source: str = "binance",
    bars: int = 20000,
) -> pd.DataFrame:
    conn = sqlite3.connect(db)
    try:
        df = pd.read_sql(
            "SELECT ts_ms, open, high, low, close, volume FROM market_ohlcv "
            "WHERE symbol=? AND timeframe=? AND source=? "
            "AND (is_complete=1 OR is_complete IS NULL) ORDER BY ts_ms",
            conn,
            params=(symbol, timeframe, source),
        )
    finally:
        conn.close()
    if df.empty:
        raise SystemExit(f"no OHLCV rows for {symbol} {timeframe} source={source} in {db}")
    df["timestamp"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    df = df.set_index("timestamp").sort_index().drop(columns=["ts_ms"])
    if bars and len(df) > bars:
        df = df.iloc[-bars:].copy()
    return df


def main(argv: list[str] | None = None) -> int:
    prefer_botsgeneral_leakage()

    ap = argparse.ArgumentParser(
        prog="leakage-check",
        description=(
            "Shared look-ahead / data-leakage audit. "
            "Separate train/test DBs are hardening only — "
            "prefix-invariance is the decisive check."
        ),
    )
    ap.add_argument(
        "--ohlcv-db",
        default=r"D:\projectsdata\candles\market_ohlcv.sqlite",
        help="SQLite market_ohlcv warehouse",
    )
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--source", default="binance")
    ap.add_argument("--bars", type=int, default=20000)
    ap.add_argument(
        "--builder",
        required=False,
        help="module.path:callable that accepts (ohlcv, *, interval=...) -> DataFrame",
    )
    ap.add_argument(
        "--registry",
        default="database/leakage_registry.json",
        help="JSON path for LEAKAGE_POTENTIAL marks",
    )
    ap.add_argument("--cuts", type=int, default=3)
    ap.add_argument("--compare-rows", type=int, default=300)
    ap.add_argument("--train-db", default=None)
    ap.add_argument("--test-db", default=None)
    ap.add_argument("--min-gap-ms", type=int, default=0)
    ap.add_argument("--ts-col", default="ts_ms")
    ap.add_argument(
        "--no-forward-corr",
        action="store_true",
        help="skip advisory/hard forward-return correlation scan",
    )
    args = ap.parse_args(argv)

    ohlcv = None
    builder = None
    if args.builder:
        builder = _load_builder(args.builder)
        ohlcv = _load_ohlcv(
            Path(args.ohlcv_db),
            args.symbol,
            args.timeframe,
            source=args.source,
            bars=args.bars,
        )
        print(
            f"ohlcv bars={len(ohlcv)}  "
            f"{ohlcv.index.min()} -> {ohlcv.index.max()}  "
            f"builder={args.builder}"
        )
    elif not (args.train_db and args.test_db):
        ap.error("provide --builder (for causal checks) and/or --train-db + --test-db")

    report = run_leakage_audit(
        ohlcv=ohlcv,
        build_features=builder,
        interval=args.timeframe,
        registry_path=args.registry,
        symbol=args.symbol,
        timeframe=args.timeframe,
        cuts=args.cuts,
        compare_rows=args.compare_rows,
        train_path=args.train_db,
        test_path=args.test_db,
        min_gap_ms=args.min_gap_ms,
        ts_col=args.ts_col,
        run_forward_corr=not args.no_forward_corr,
    )
    print(format_report(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
