"""Download all research candles into D:\\projectsdata\\candles\\market_ohlcv.sqlite.

Usage:
  python -m botsgeneral.research_candles.download_all
  python -m botsgeneral.research_candles.download_all --only binance
  python -m botsgeneral.research_candles.download_all --only dukascopy,yahoo,btcd
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import traceback
from datetime import datetime, timezone

from botsgeneral.research_candles.db import ResearchCandleDB
from botsgeneral.research_candles.fetch_binance import BinanceBlockedError, fetch_klines
from botsgeneral.research_candles.fetch_binance_vision import fetch_klines_vision
from botsgeneral.research_candles.fetch_btcd import (
    IMPORT_DIR,
    fetch_coingecko_btcd_daily,
    ingest_import_dir,
)
from botsgeneral.research_candles.fetch_dukascopy import fetch_dukascopy
from botsgeneral.research_candles.fetch_yahoo import fetch_yahoo
from botsgeneral.research_candles.resample import (
    derive_1w_from_1d,
    derive_4h_from_1h,
    derive_higher_from_1m,
)
from botsgeneral.research_candles.universe import (
    BINANCE_ALLOWED_TIMEFRAMES,
    BINANCE_FUTURES_SYMBOLS,
    BINANCE_TIMEFRAMES,
    DUKASCOPY,
    DUKASCOPY_NATIVE_TFS,
    YAHOO,
)

log = logging.getLogger("research_candles")


def _download_dukascopy(
    db: ResearchCandleDB,
    *,
    incremental: bool,
    symbols: set[str] | None = None,
    timeframes: set[str] | None = None,
) -> list[str]:
    notes: list[str] = []
    now = datetime.now(timezone.utc)
    tfs = tuple(tf for tf in DUKASCOPY_NATIVE_TFS if timeframes is None or tf in timeframes)
    for inst in DUKASCOPY:
        if symbols is not None and inst.symbol not in symbols:
            continue
        for tf in tfs:
            start = inst.start
            if incremental:
                last = db.latest_ts_ms("dukascopy", inst.symbol, tf)
                if last is not None:
                    # overlap one bar
                    from datetime import timedelta

                    start = max(
                        inst.start,
                        datetime.fromtimestamp(last / 1000, tz=timezone.utc) - timedelta(days=2),
                    )
            try:
                df = fetch_dukascopy(inst.instrument, tf, start, now)
                n = db.upsert_df(
                    df,
                    source="dukascopy",
                    symbol=inst.symbol,
                    timeframe=tf,
                    price_type="bid",
                )
                log.info("upsert dukascopy %s %s -> %s", inst.symbol, tf, n)
            except Exception as e:
                msg = f"dukascopy {inst.symbol} {tf}: {e}"
                log.error(msg)
                notes.append(msg)
                traceback.print_exc()

        # derive 4h from 1h, 1w from 1d
        df_1h = db.load(inst.symbol, "1h", source="dukascopy")
        if not df_1h.empty:
            df_4h = derive_4h_from_1h(df_1h)
            db.upsert_df(df_4h, source="dukascopy", symbol=inst.symbol, timeframe="4h", price_type="bid")
        df_1d = db.load(inst.symbol, "1d", source="dukascopy")
        if not df_1d.empty:
            df_1w = derive_1w_from_1d(df_1d)
            db.upsert_df(df_1w, source="dukascopy", symbol=inst.symbol, timeframe="1w", price_type="bid")
    return notes


def _download_yahoo(
    db: ResearchCandleDB,
    *,
    symbols: set[str] | None = None,
    timeframes: set[str] | None = None,
) -> list[str]:
    notes: list[str] = []
    tfs = tuple(tf for tf in ("1d", "1w", "1h") if timeframes is None or tf in timeframes)
    for inst in YAHOO:
        if symbols is not None and inst.symbol not in symbols:
            continue
        for tf in tfs:
            try:
                df = fetch_yahoo(inst.yahoo, tf)
                if df.empty:
                    continue
                n = db.upsert_df(df, source="yahoo", symbol=inst.symbol, timeframe=tf, price_type="last")
                log.info("upsert yahoo %s %s -> %s", inst.symbol, tf, n)
            except Exception as e:
                # 1h often unavailable for indices — soft fail
                msg = f"yahoo {inst.symbol} {tf}: {e}"
                log.warning(msg)
                notes.append(msg)
        # derive 4h from yahoo 1h when present
        df_1h = db.load(inst.symbol, "1h", source="yahoo")
        if not df_1h.empty and (timeframes is None or "4h" in timeframes):
            db.upsert_df(
                derive_4h_from_1h(df_1h),
                source="yahoo",
                symbol=inst.symbol,
                timeframe="4h",
                price_type="last",
            )
    return notes


def _resolve_binance_symbols(symbols: set[str] | None) -> tuple[str, ...]:
    """Universe symbols, plus any explicitly requested symbols not yet listed."""
    if symbols is None:
        return BINANCE_FUTURES_SYMBOLS
    ordered = [s for s in BINANCE_FUTURES_SYMBOLS if s in symbols]
    extra = sorted(s for s in symbols if s not in set(BINANCE_FUTURES_SYMBOLS))
    return tuple(ordered + extra)


def _resolve_binance_timeframes(timeframes: set[str] | None) -> tuple[str, ...]:
    if timeframes is None:
        return BINANCE_TIMEFRAMES
    allowed = set(BINANCE_ALLOWED_TIMEFRAMES)
    unknown = sorted(tf for tf in timeframes if tf not in allowed)
    if unknown:
        raise ValueError(f"Unsupported Binance timeframes: {unknown}")
    # preserve a sensible order
    order = list(BINANCE_ALLOWED_TIMEFRAMES)
    return tuple(tf for tf in order if tf in timeframes)


def _binance_db_source(price_type: str) -> str:
    return "binance_mark" if price_type == "mark" else "binance"


def _binance_contract_metadata(price_type: str) -> tuple[str, str, str]:
    """Return canonical price_type, product, endpoint for USDⓈ-M futures."""
    if price_type == "mark":
        return "mark_price", "USDⓈ-M", "/fapi/v1/markPriceKlines"
    return "last_price", "USDⓈ-M", "/fapi/v1/klines"


def _download_binance(
    db: ResearchCandleDB,
    *,
    incremental: bool,
    symbols: set[str] | None = None,
    timeframes: set[str] | None = None,
    price_types: tuple[str, ...] = ("last",),
) -> list[str]:
    notes: list[str] = []
    blocked = False
    try:
        tfs = _resolve_binance_timeframes(timeframes)
    except ValueError as e:
        notes.append(str(e))
        log.error("%s", e)
        return notes
    syms = _resolve_binance_symbols(symbols)
    derive_from_1m = "1m" in tfs

    for price_type in price_types:
        if price_type not in ("last", "mark"):
            notes.append(f"unsupported price_type: {price_type}")
            continue
        source = _binance_db_source(price_type)
        stored_price_type, product, source_endpoint = _binance_contract_metadata(price_type)
        for symbol in syms:
            for tf in tfs:
                start_ms = None
                if incremental:
                    last = db.latest_ts_ms(source, symbol, tf)
                    if last is not None:
                        # tighter overlap for 1m (6h); 5d for coarser TFs
                        overlap_ms = 6 * 3_600_000 if tf == "1m" else 5 * 86_400_000
                        start_ms = last - overlap_ms
                use_vision = not incremental or start_ms is None or start_ms < 1_600_000_000_000
                try:
                    # Prefer Vision for deep history (REST often geo-blocked); soft-fills recent via REST.
                    if use_vision:
                        df = fetch_klines_vision(
                            symbol,
                            tf,
                            market="binance",
                            price_type=price_type,  # type: ignore[arg-type]
                            start_ms=start_ms,
                        )
                    else:
                        df = fetch_klines(
                            symbol,
                            tf,
                            market="binance",
                            price_type=price_type,  # type: ignore[arg-type]
                            start_ms=start_ms,
                        )
                    n = db.upsert_df(
                        df,
                        source=source,
                        symbol=symbol,
                        timeframe=tf,
                        price_type=stored_price_type,
                        product=product,
                        source_endpoint=source_endpoint,
                    )
                    log.info("upsert %s %s %s -> %s", source, symbol, tf, n)
                except BinanceBlockedError as e:
                    # If REST-only path is blocked, fall back to Vision once.
                    if use_vision:
                        blocked = True
                        notes.append(str(e))
                        log.error("%s", e)
                        return notes
                    log.warning("REST blocked for %s %s; falling back to Vision. %s", symbol, tf, e)
                    try:
                        df = fetch_klines_vision(
                            symbol,
                            tf,
                            market="binance",
                            price_type=price_type,  # type: ignore[arg-type]
                            start_ms=start_ms,
                        )
                        n = db.upsert_df(
                            df,
                            source=source,
                            symbol=symbol,
                            timeframe=tf,
                            price_type=stored_price_type,
                            product=product,
                            source_endpoint=source_endpoint,
                        )
                        log.info("upsert %s %s %s (Vision fallback) -> %s", source, symbol, tf, n)
                        notes.append(
                            "REMINDER: Activate VPN for live REST gap fill; Vision archives stop at yesterday."
                        )
                    except Exception as e2:
                        blocked = True
                        notes.append(str(e2))
                        log.error("%s", e2)
                        return notes
                except Exception as e:
                    msg = f"{source} {symbol} {tf}: {e}"
                    log.error(msg)
                    notes.append(msg)

            if derive_from_1m:
                df_1m = db.load(symbol, "1m", source=source)
                if df_1m.empty:
                    notes.append(f"{source} {symbol}: no 1m bars to derive from")
                    continue
                derived = derive_higher_from_1m(df_1m)
                for tf, df in derived.items():
                    n = db.upsert_df(
                        df,
                        source=source,
                        symbol=symbol,
                        timeframe=tf,
                        price_type=stored_price_type,
                        product=product,
                        source_endpoint=source_endpoint,
                    )
                    log.info("derived %s %s %s from 1m -> %s", source, symbol, tf, n)

    if blocked:
        notes.append("REMINDER: Activate VPN to reach Binance, then re-run --only binance")
    return notes


def _download_btcd(db: ResearchCandleDB) -> list[str]:
    notes: list[str] = []
    # TradingView imports first (authoritative for BTC.D methodology)
    imported = ingest_import_dir()
    for tf, df in imported.items():
        n = db.upsert_df(df, source="tradingview", symbol="BTC.D", timeframe=tf, price_type="last")
        log.info("upsert tradingview BTC.D %s -> %s", tf, n)
    if not imported:
        notes.append(
            f"No TradingView BTC.D CSV found. Export CRYPTOCAP:BTC.D (1h/4h/1d) into {IMPORT_DIR}"
        )
    # CoinGecko approximate daily
    try:
        df = fetch_coingecko_btcd_daily()
        if not df.empty:
            n = db.upsert_df(df, source="coingecko", symbol="BTC.D", timeframe="1d", price_type="last")
            log.info("upsert coingecko BTC.D 1d -> %s", n)
            db.upsert_df(
                derive_1w_from_1d(df),
                source="coingecko",
                symbol="BTC.D",
                timeframe="1w",
                price_type="last",
            )
        else:
            notes.append("CoinGecko BTC.D daily unavailable (rate limit or plan)")
    except Exception as e:
        notes.append(f"coingecko BTC.D: {e}")
    return notes


def run(
    only: set[str] | None = None,
    incremental: bool = True,
    symbols: set[str] | None = None,
    timeframes: set[str] | None = None,
    price_types: tuple[str, ...] = ("last",),
) -> int:
    only = only or {"dukascopy", "yahoo", "binance", "btcd"}
    db = ResearchCandleDB()
    t0 = time.time()
    all_notes: list[str] = []
    log.info("DB: %s", db.path)

    if "dukascopy" in only:
        log.info("=== Dukascopy macro/FX/commodities ===")
        all_notes.extend(
            _download_dukascopy(
                db,
                incremental=incremental,
                symbols=symbols,
                timeframes=timeframes,
            )
        )
    if "yahoo" in only:
        log.info("=== Yahoo daily/weekly cross-checks ===")
        all_notes.extend(_download_yahoo(db, symbols=symbols, timeframes=timeframes))
    if "binance" in only:
        log.info("=== Binance futures price_types=%s ===", ",".join(price_types))
        all_notes.extend(
            _download_binance(
                db,
                incremental=incremental,
                symbols=symbols,
                timeframes=timeframes,
                price_types=price_types,
            )
        )
    if "btcd" in only:
        log.info("=== BTC.D ===")
        all_notes.extend(_download_btcd(db))

    cov = db.coverage()
    summary = {
        "db": str(db.path),
        "elapsed_sec": round(time.time() - t0, 1),
        "series": int(len(cov)),
        "total_bars": int(cov["bars"].sum()) if not cov.empty else 0,
        "notes": all_notes,
        "coverage_preview": cov.head(40).to_dict(orient="records") if not cov.empty else [],
    }
    db.set_meta("last_download_summary", json.dumps(summary, default=str))
    db.set_meta("last_download_at", datetime.now(timezone.utc).isoformat())
    # write human-readable coverage
    cov_path = db.path.parent / "coverage.csv"
    if not cov.empty:
        cov.to_csv(cov_path, index=False)
    print(json.dumps({k: summary[k] for k in ("db", "elapsed_sec", "series", "total_bars", "notes")}, indent=2))
    if not cov.empty:
        print(cov.to_string(index=False))
    db.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Download shared research candles")
    p.add_argument(
        "--only",
        default="dukascopy,yahoo,binance,btcd",
        help="Comma list: dukascopy,yahoo,binance,btcd",
    )
    p.add_argument("--full", action="store_true", help="Ignore incremental cursors; refetch from instrument start")
    p.add_argument(
        "--symbols",
        default="",
        help="Optional comma list of symbols to update only (e.g. BTCUSDT,ETHUSDT or DXY,XAUUSD)",
    )
    p.add_argument(
        "--timeframes",
        default="",
        help="Optional comma list of timeframes to update only (e.g. 5m,1h,4h,1d,1w)",
    )
    p.add_argument(
        "--price-type",
        default="last",
        help="Binance only: last, mark, or both (comma). Mark stored as source=binance_mark",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    only = {x.strip().lower() for x in args.only.split(",") if x.strip()}
    symbols = {x.strip().upper() for x in args.symbols.split(",") if x.strip()} or None
    timeframes = {x.strip().lower() for x in args.timeframes.split(",") if x.strip()} or None
    raw_pt = [x.strip().lower() for x in args.price_type.split(",") if x.strip()]
    if "both" in raw_pt:
        price_types = ("last", "mark")
    else:
        price_types = tuple(raw_pt) or ("last",)
    return run(
        only=only,
        incremental=not args.full,
        symbols=symbols,
        timeframes=timeframes,
        price_types=price_types,
    )


if __name__ == "__main__":
    sys.exit(main())
