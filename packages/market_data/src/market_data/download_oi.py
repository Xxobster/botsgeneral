"""Download shared research open interest into market_oi.sqlite."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests

from market_data.fetch_binance_oi import (
    BinanceOIBlockedError,
    VISION_EARLIEST,
    VISION_DEFAULT_START,
    discover_usdt_perpetuals as discover_binance,
    fetch_binance_oi_hist,
    fetch_binance_oi_vision,
    prioritize_symbols,
)
from market_data.fetch_bybit_oi import (
    BYBIT_EARLIEST,
    BYBIT_DEFAULT_START,
    BybitOIError,
    discover_usdt_perpetuals as discover_bybit,
    fetch_bybit_oi,
)
from market_data.oi_db import ResearchOIDB
from market_data.universe import BINANCE_FUTURES_SYMBOLS

log = logging.getLogger(__name__)

PREFERRED = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "ADAUSDT",
    "TRXUSDT",
    "XLMUSDT",
    "VETUSDT",
    "HYPEUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "DOTUSDT",
)

BYBIT_DEFAULT_TFS = ("1h", "1d")
BYBIT_MAJOR_TFS = ("5m", "1h", "1d")
MAJOR_5M = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def _ms_to_date(ts_ms: int) -> date:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).date()


def _resolve_symbols(
    *,
    symbols: set[str] | None,
    all_symbols: bool,
    exchange: str,
) -> list[str]:
    if symbols:
        base = sorted(symbols)
    elif all_symbols:
        if exchange == "binance":
            base = discover_binance()
        else:
            base = discover_bybit()
        log.info("Discovered %s %s USDT perps", len(base), exchange)
    else:
        base = list(BINANCE_FUTURES_SYMBOLS)
    return prioritize_symbols(base, PREFERRED)


def download_binance(
    db: ResearchOIDB,
    symbols: list[str],
    *,
    incremental: bool = True,
    workers: int = 6,
    tip_only: bool = False,
) -> dict:
    sess = requests.Session()
    summary = {"exchange": "binance", "symbols": 0, "rows": 0, "errors": []}
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)

    for symbol in symbols:
        summary["symbols"] += 1
        try:
            if not tip_only:
                start = VISION_EARLIEST.get(symbol, VISION_DEFAULT_START)
                if incremental:
                    last = db.max_ts_ms("binance", symbol, "5m")
                    if last is not None:
                        start = max(start, _ms_to_date(last) - timedelta(days=2))
                if start <= yesterday:
                    day_rows = {"n": 0}

                    def _on_day(_day: date, frame: pd.DataFrame, _sym=symbol) -> None:
                        n = db.upsert_df(
                            frame,
                            exchange="binance",
                            symbol=_sym,
                            timeframe="5m",
                            source_endpoint="data.binance.vision/futures/um/daily/metrics",
                        )
                        day_rows["n"] += n

                    fetch_binance_oi_vision(
                        symbol,
                        start=start,
                        end=yesterday,
                        workers=workers,
                        session=sess,
                        on_day=_on_day,
                    )
                    summary["rows"] += day_rows["n"]
                    log.info("upsert binance %s 5m vision -> %s", symbol, day_rows["n"])

            tip_start = None
            if incremental:
                last = db.max_ts_ms("binance", symbol, "5m")
                if last is not None:
                    tip_start = last + 1
            tip = fetch_binance_oi_hist(
                symbol, "5m", start_ms=tip_start, session=sess
            )
            n = db.upsert_df(
                tip,
                exchange="binance",
                symbol=symbol,
                timeframe="5m",
                source_endpoint="/futures/data/openInterestHist",
            )
            summary["rows"] += n
            if n:
                log.info("upsert binance %s 5m tip -> %s", symbol, n)
        except BinanceOIBlockedError as e:
            summary["errors"].append(str(e))
            log.error("%s", e)
            # Continue other symbols; Vision may recover after a pause.
            time.sleep(2.0)
            continue
        except Exception as e:
            msg = f"binance {symbol}: {e}"
            summary["errors"].append(msg)
            log.exception(msg)
    return summary


def download_bybit(
    db: ResearchOIDB,
    symbols: list[str],
    timeframes: tuple[str, ...] = BYBIT_DEFAULT_TFS,
    *,
    incremental: bool = True,
) -> dict:
    sess = requests.Session()
    summary = {"exchange": "bybit", "symbols": 0, "rows": 0, "errors": []}
    now = datetime.now(timezone.utc)

    for symbol in symbols:
        summary["symbols"] += 1
        tfs = list(timeframes)
        if symbol in MAJOR_5M and "5m" not in tfs:
            tfs = ["5m", *tfs]
        for tf in tfs:
            try:
                start = BYBIT_EARLIEST.get(symbol, BYBIT_DEFAULT_START)
                end = now
                expected_start_ms = int(
                    datetime(
                        start.year, start.month, start.day, tzinfo=timezone.utc
                    ).timestamp()
                    * 1000
                )
                if incremental:
                    last = db.max_ts_ms("bybit", symbol, tf)
                    first = db.min_ts_ms("bybit", symbol, tf)
                    # Newest-first pagination can leave a high max_ts with a late min_ts
                    # if a prior run was interrupted — force full history in that case.
                    incomplete = (
                        first is not None and first > expected_start_ms + 7 * 86_400_000
                    )
                    if last is not None and not incomplete:
                        start_ms = last - {
                            "5m": 5 * 60_000,
                            "15m": 15 * 60_000,
                            "30m": 30 * 60_000,
                            "1h": 60 * 60_000,
                            "4h": 4 * 60 * 60_000,
                            "1d": 24 * 60 * 60_000,
                        }.get(tf, 60_000)
                        start = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
                    elif incomplete:
                        log.warning(
                            "bybit %s %s incomplete history (min=%s); full refetch",
                            symbol,
                            tf,
                            first,
                        )
                df = fetch_bybit_oi(
                    symbol, tf, start=start, end=end, session=sess
                )
                n = db.upsert_df(
                    df,
                    exchange="bybit",
                    symbol=symbol,
                    timeframe=tf,
                    source_endpoint="/v5/market/open-interest",
                )
                summary["rows"] += n
                log.info("upsert bybit %s %s -> %s", symbol, tf, n)
            except BybitOIError as e:
                summary["errors"].append(str(e))
                log.warning("%s", e)
            except Exception as e:
                msg = f"bybit {symbol} {tf}: {e}"
                summary["errors"].append(msg)
                log.exception(msg)
    return summary


def run(
    *,
    only: set[str] | None = None,
    symbols: set[str] | None = None,
    all_symbols: bool = False,
    incremental: bool = True,
    bybit_timeframes: tuple[str, ...] = BYBIT_DEFAULT_TFS,
    vision_workers: int = 12,
    tip_only: bool = False,
    db_path: str | None = None,
) -> int:
    only = only or {"binance", "bybit"}
    t0 = time.time()
    db = ResearchOIDB(db_path)
    summary: dict = {
        "db": str(db.path),
        "notes": [
            "oi = base-asset open interest (Bybit: singleOpenInterest; Binance: sum_open_interest)",
            "oi_usd = USD notional when provided by Binance",
            "oi_sum = Bybit openInterest (both sides) when present",
            "UNIQUE(exchange, symbol, timeframe, ts_ms)",
        ],
        "parts": [],
    }

    if "binance" in only:
        syms = _resolve_symbols(symbols=symbols, all_symbols=all_symbols, exchange="binance")
        # When --all, still do full Vision for preferred research set; tip-only for the rest
        if all_symbols and not symbols:
            full = [s for s in syms if s in set(PREFERRED) or s in set(BINANCE_FUTURES_SYMBOLS)]
            rest = [s for s in syms if s not in set(full)]
            log.info("Binance full Vision for %s majors; tip-only for %s others", len(full), len(rest))
            part = download_binance(
                db, full, incremental=incremental, workers=vision_workers, tip_only=tip_only
            )
            summary["parts"].append(part)
            part2 = download_binance(
                db, rest, incremental=incremental, workers=vision_workers, tip_only=True
            )
            summary["parts"].append({**part2, "mode": "tip_only"})
        else:
            part = download_binance(
                db, syms, incremental=incremental, workers=vision_workers, tip_only=tip_only
            )
            summary["parts"].append(part)

    if "bybit" in only:
        syms = _resolve_symbols(symbols=symbols, all_symbols=all_symbols, exchange="bybit")
        if all_symbols and not symbols:
            full = [s for s in syms if s in set(PREFERRED) or s in set(BINANCE_FUTURES_SYMBOLS)]
            rest = [s for s in syms if s not in set(full)]
            # Majors: full history at requested TFs; rest: 1d only (manageable)
            part = download_bybit(
                db, full, bybit_timeframes, incremental=incremental
            )
            summary["parts"].append(part)
            part2 = download_bybit(
                db, rest, ("1d",), incremental=incremental
            )
            summary["parts"].append({**part2, "mode": "1d_all"})
        else:
            part = download_bybit(
                db, syms, bybit_timeframes, incremental=incremental
            )
            summary["parts"].append(part)

    cov = db.coverage()
    summary["elapsed_sec"] = round(time.time() - t0, 1)
    summary["series"] = int(len(cov))
    summary["total_bars"] = int(cov["bars"].sum()) if not cov.empty else 0
    db.set_meta("last_oi_download_at", datetime.now(timezone.utc).isoformat())
    cov_path = db.path.parent / "oi_coverage.csv"
    if not cov.empty:
        cov.to_csv(cov_path, index=False)
    print(
        json.dumps(
            {
                k: summary[k]
                for k in ("db", "elapsed_sec", "series", "total_bars", "notes", "parts")
            },
            indent=2,
            default=str,
        )
    )
    if not cov.empty:
        # show preferred first
        pref = cov[cov["symbol"].isin(PREFERRED)].copy()
        print(pref.to_string(index=False) if not pref.empty else cov.head(40).to_string(index=False))
    db.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Download shared research open interest")
    p.add_argument(
        "--only",
        default="binance,bybit",
        help="Comma list: binance,bybit",
    )
    p.add_argument("--full", action="store_true", help="Ignore incremental cursors")
    p.add_argument(
        "--symbols",
        default="",
        help="Optional comma list (e.g. BTCUSDT,ETHUSDT,SOLUSDT)",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="Discover all listed USDT linear perps (majors get full history; others tip/1d)",
    )
    p.add_argument(
        "--bybit-timeframes",
        default="1h,1d",
        help="Bybit intervals (default 1h,1d; 5m auto-added for BTC/ETH/SOL)",
    )
    p.add_argument("--workers", type=int, default=6, help="Vision concurrent day downloads")
    p.add_argument("--tip-only", action="store_true", help="Binance: skip Vision, REST tip only")
    p.add_argument("--db", default=None, help="Override SQLite path")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    only = {x.strip().lower() for x in args.only.split(",") if x.strip()}
    symbols = {x.strip().upper() for x in args.symbols.split(",") if x.strip()} or None
    btfs = tuple(x.strip().lower() for x in args.bybit_timeframes.split(",") if x.strip())
    return run(
        only=only,
        symbols=symbols,
        all_symbols=args.all,
        incremental=not args.full,
        bybit_timeframes=btfs or BYBIT_DEFAULT_TFS,
        vision_workers=args.workers,
        tip_only=args.tip_only,
        db_path=args.db,
    )


if __name__ == "__main__":
    sys.exit(main())
