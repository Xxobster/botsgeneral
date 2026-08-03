"""CLI for the shared indicators warehouse.

Examples::

  indicators coverage
  indicators update --symbol BTCUSDT --timeframe 1h
  indicators update-all
  indicators update-all --timeframes 1h,4h,1d
  indicators update-all --refresh
  indicators show --symbol BTCUSDT --timeframe 1h --table bar_features
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .candles import DEFAULT_STRUCTURE_TIMEFRAMES, open_candle_db
from .compute import DEFAULT_SWING_LEFT, DEFAULT_SWING_RIGHT
from .paths import candles_db, indicators_db
from .store import IndicatorDB
from .update import update_all, update_series


def _split(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [p.strip() for p in raw.split(",") if p.strip()]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="indicators",
        description="Shared Fibonacci price-structure indicator warehouse",
    )
    p.add_argument("--db", type=Path, default=None, help="indicators.sqlite path")
    p.add_argument("--candles-db", type=Path, default=None, help="market_ohlcv.sqlite path")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("coverage", help="list series already in the indicators DB")
    sub.add_parser("paths", help="print default warehouse paths")

    p_one = sub.add_parser("update", help="compute/update one symbol+timeframe")
    p_one.add_argument("--symbol", required=True)
    p_one.add_argument("--timeframe", required=True)
    p_one.add_argument("--source", default=None)
    p_one.add_argument("--swing-left", type=int, default=DEFAULT_SWING_LEFT)
    p_one.add_argument("--swing-right", type=int, default=DEFAULT_SWING_RIGHT)

    p_all = sub.add_parser("update-all", help="compute/update every matching candle series")
    p_all.add_argument("--symbols", default=None, help="comma list; default=all in warehouse")
    p_all.add_argument(
        "--timeframes",
        default=",".join(DEFAULT_STRUCTURE_TIMEFRAMES),
        help=f"comma list (default {','.join(DEFAULT_STRUCTURE_TIMEFRAMES)}; "
        "add 15m as needed; use 'all' for every TF including 1m/5m)",
    )
    p_all.add_argument("--sources", default=None, help="comma list of candle sources")
    p_all.add_argument("--swing-left", type=int, default=DEFAULT_SWING_LEFT)
    p_all.add_argument("--swing-right", type=int, default=DEFAULT_SWING_RIGHT)
    p_all.add_argument("--min-bars", type=int, default=50)
    p_all.add_argument(
        "--refresh",
        action="store_true",
        help="refresh research candles via market_data before computing",
    )
    p_all.add_argument("--quiet", action="store_true")

    p_show = sub.add_parser("show", help="print a table slice for programs to inspect")
    p_show.add_argument("--symbol", required=True)
    p_show.add_argument("--timeframe", required=True)
    p_show.add_argument("--source", default=None)
    p_show.add_argument(
        "--table",
        default="bar_features",
        choices=["bar_features", "swings", "legs", "levels", "structure_events"],
    )
    p_show.add_argument("--swing-left", type=int, default=DEFAULT_SWING_LEFT)
    p_show.add_argument("--swing-right", type=int, default=DEFAULT_SWING_RIGHT)
    p_show.add_argument("--tail", type=int, default=20)

    args = p.parse_args(argv)
    ind_path = args.db or indicators_db()
    cndl_path = args.candles_db or candles_db()

    if args.cmd == "paths":
        print(f"indicators_db: {ind_path}")
        print(f"candles_db:    {cndl_path}")
        return 0

    if args.cmd == "coverage":
        with IndicatorDB(ind_path) as db:
            cov = db.coverage()
        if cov.empty:
            print("(empty)")
        else:
            print(cov.to_string(index=False))
            print(f"\n{len(cov)} series in {ind_path}")
        return 0

    if args.cmd == "update":
        ind = IndicatorDB(ind_path)
        cdb = open_candle_db(cndl_path)
        try:
            res = update_series(
                args.symbol.upper(),
                args.timeframe,
                source=args.source,
                swing_left=args.swing_left,
                swing_right=args.swing_right,
                indicator_db=ind,
                candle_db=cdb,
            )
        finally:
            ind.close()
            cdb.close()
        if res.error:
            print(f"ERROR {res.symbol} {res.timeframe}: {res.error}", file=sys.stderr)
            return 1
        print(
            f"OK {res.source} {res.symbol} {res.timeframe}: "
            f"bars={res.n_bars} swings={res.n_swings} counts={res.counts}"
        )
        print(f"db: {ind_path}")
        return 0

    if args.cmd == "update-all":
        tfs = _split(args.timeframes)
        if tfs and len(tfs) == 1 and tfs[0].lower() == "all":
            tfs = None
        results = update_all(
            symbols=_split(args.symbols),
            timeframes=tfs,
            sources=_split(args.sources),
            swing_left=args.swing_left,
            swing_right=args.swing_right,
            min_bars=args.min_bars,
            refresh=bool(args.refresh),
            indicator_path=ind_path,
            candle_path=cndl_path,
            progress=not args.quiet,
        )
        n_err = sum(1 for r in results if r.error)
        print(
            f"\nDone: {len(results)} series, {n_err} errors -> {ind_path}",
            flush=True,
        )
        return 1 if n_err else 0

    if args.cmd == "show":
        with IndicatorDB(ind_path) as db:
            loaders = {
                "bar_features": db.load_bar_features,
                "swings": db.load_swings,
                "legs": db.load_legs,
                "levels": db.load_levels,
                "structure_events": db.load_structure_events,
            }
            df = loaders[args.table](
                args.symbol.upper(),
                args.timeframe,
                source=args.source,
                swing_left=args.swing_left,
                swing_right=args.swing_right,
            )
        if df.empty:
            print("(empty — run indicators update first)")
            return 1
        print(df.tail(args.tail).to_string(index=False))
        print(f"\n{len(df)} rows")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
