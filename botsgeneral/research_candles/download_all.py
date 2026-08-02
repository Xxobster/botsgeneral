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
from botsgeneral.research_candles.fetch_crypto_macro import (
    STABLECOIN_SYMBOLS,
    build_dominance_pct,
    fetch_blockchain_btc_mcap_daily,
    fetch_coingecko_coin_mcap_daily,
    fetch_coingecko_total_mcap_daily,
    fetch_defillama_stable_mcap_daily,
    fetch_defillama_stablecoin_asset_daily,
    fetch_fear_greed_daily,
    resolve_stablecoin_ids,
    stablecoin_flow_from_mcap,
)
from botsgeneral.research_candles.fetch_dukascopy import fetch_dukascopy
from botsgeneral.research_candles.fetch_fred import fetch_fred_daily
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
    FRED,
    YAHOO,
)

log = logging.getLogger("research_candles")

# Skip network fetch when the warehouse already has a recent bar for that series.
_FRESH_HOURS = {
    "1m": 2,
    "5m": 2,
    "15m": 4,
    "1h": 6,
    "4h": 18,
    "1d": 40,   # covers weekends for daily macros
    "1w": 8 * 24,
}


def _series_is_fresh(
    db: ResearchCandleDB,
    source: str,
    symbol: str,
    timeframe: str,
    *,
    max_age_hours: float | None = None,
) -> bool:
    last = db.latest_ts_ms(source, symbol, timeframe)
    if last is None:
        return False
    age_h = (time.time() * 1000 - last) / 3_600_000.0
    limit = max_age_hours if max_age_hours is not None else float(_FRESH_HOURS.get(timeframe, 24))
    if age_h <= limit:
        log.info(
            "skip fresh %s %s %s (age=%.1fh <= %.1fh)",
            source,
            symbol,
            timeframe,
            age_h,
            limit,
        )
        return True
    return False


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
    incremental: bool = True,
) -> list[str]:
    notes: list[str] = []
    tfs = tuple(tf for tf in ("1d", "1w", "1h") if timeframes is None or tf in timeframes)
    for inst in YAHOO:
        if symbols is not None and inst.symbol not in symbols:
            continue
        for tf in tfs:
            if incremental and _series_is_fresh(db, "yahoo", inst.symbol, tf):
                continue
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


def _upsert_daily_series(
    db: ResearchCandleDB,
    df,
    *,
    source: str,
    symbol: str,
    price_type: str = "last",
    also_1w: bool = True,
) -> int:
    if df is None or df.empty:
        return 0
    n = db.upsert_df(df, source=source, symbol=symbol, timeframe="1d", price_type=price_type)
    if also_1w:
        db.upsert_df(
            derive_1w_from_1d(df),
            source=source,
            symbol=symbol,
            timeframe="1w",
            price_type=price_type,
        )
    return n


def _download_fred(
    db: ResearchCandleDB,
    *,
    symbols: set[str] | None = None,
    incremental: bool = True,
) -> list[str]:
    notes: list[str] = []
    for inst in FRED:
        if symbols is not None and inst.symbol not in symbols:
            continue
        if incremental and _series_is_fresh(db, "fred", inst.symbol, "1d"):
            continue
        try:
            df = fetch_fred_daily(inst.series_id)
            n = _upsert_daily_series(db, df, source="fred", symbol=inst.symbol)
            log.info("upsert fred %s (%s) -> %s", inst.symbol, inst.series_id, n)
            if n == 0:
                notes.append(f"fred {inst.symbol}: empty")
        except Exception as e:
            msg = f"fred {inst.symbol}: {e}"
            log.error(msg)
            notes.append(msg)
    return notes


def _download_crypto_macro(
    db: ResearchCandleDB,
    *,
    symbols: set[str] | None = None,
    incremental: bool = True,
) -> list[str]:
    """BTC/ETH/TOTAL mcap, dominance, stablecoin mcap/flows, Fear & Greed."""
    notes: list[str] = []

    def want(sym: str) -> bool:
        return symbols is None or sym in symbols

    def fresh(source: str, symbol: str) -> bool:
        return incremental and _series_is_fresh(db, source, symbol, "1d")

    btc_mcap = eth_mcap = tot_mcap = None
    try:
        if want("BTC_MCAP") or want("BTC.D") or want("TOTAL_MCAP"):
            if fresh("blockchain", "BTC_MCAP") or fresh("coingecko", "BTC_MCAP"):
                btc_mcap = db.load("BTC_MCAP", "1d")
            else:
                # Long history from blockchain.info, recent fill from CoinGecko.
                frames = []
                try:
                    frames.append(fetch_blockchain_btc_mcap_daily())
                except Exception as e:
                    notes.append(f"blockchain BTC_MCAP: {e}")
                try:
                    frames.append(fetch_coingecko_coin_mcap_daily("bitcoin"))
                except Exception as e:
                    notes.append(f"coingecko BTC_MCAP: {e}")
                frames = [f for f in frames if f is not None and not f.empty]
                if frames:
                    import pandas as pd

                    btc_mcap = (
                        pd.concat(frames, ignore_index=True)
                        .drop_duplicates("ts_ms", keep="last")
                        .sort_values("ts_ms")
                        .reset_index(drop=True)
                    )
                if want("BTC_MCAP") and btc_mcap is not None and not btc_mcap.empty:
                    n = _upsert_daily_series(db, btc_mcap, source="coingecko", symbol="BTC_MCAP")
                    n2 = _upsert_daily_series(db, btc_mcap, source="blockchain", symbol="BTC_MCAP")
                    log.info("upsert BTC_MCAP coingecko=%s blockchain=%s", n, n2)
                elif want("BTC_MCAP"):
                    notes.append("BTC_MCAP empty")
            time.sleep(0.2)
        if want("ETH_MCAP") or want("ETH.D"):
            if fresh("coingecko", "ETH_MCAP"):
                eth_mcap = db.load("ETH_MCAP", "1d", source="coingecko")
            else:
                eth_mcap = fetch_coingecko_coin_mcap_daily("ethereum")
                if want("ETH_MCAP"):
                    n = _upsert_daily_series(db, eth_mcap, source="coingecko", symbol="ETH_MCAP")
                    log.info("upsert coingecko ETH_MCAP -> %s", n)
                    if n == 0:
                        notes.append("coingecko ETH_MCAP empty (rate limit?)")
            time.sleep(0.2)
        if want("TOTAL_MCAP") or want("BTC.D") or want("ETH.D"):
            if fresh("coingecko", "TOTAL_MCAP") or fresh("tradingview", "TOTAL_MCAP") or fresh("derived", "TOTAL_MCAP"):
                tot_mcap = db.load("TOTAL_MCAP", "1d")
            else:
                tot_mcap = fetch_coingecko_total_mcap_daily()
                if want("TOTAL_MCAP"):
                    n = _upsert_daily_series(db, tot_mcap, source="coingecko", symbol="TOTAL_MCAP")
                    log.info("upsert coingecko TOTAL_MCAP -> %s", n)
                    if n == 0:
                        notes.append(
                            "TOTAL_MCAP: CoinGecko global chart needs Pro. "
                            "Drop TradingView CRYPTOCAP:TOTAL CSV into "
                            r"D:\projectsdata\candles\imports\total_mcap\\"
                        )
    except Exception as e:
        notes.append(f"mcap: {e}")

    # Optional TradingView TOTAL.M CSV import (same schema as BTC.D imports)
    try:
        if want("TOTAL_MCAP"):
            from pathlib import Path
            from botsgeneral.research_candles.fetch_btcd import ingest_tradingview_csv

            total_dir = Path(r"D:\projectsdata\candles\imports\total_mcap")
            total_dir.mkdir(parents=True, exist_ok=True)
            for p in sorted(total_dir.glob("*.csv")):
                df = ingest_tradingview_csv(p)
                n = _upsert_daily_series(db, df, source="tradingview", symbol="TOTAL_MCAP")
                log.info("upsert tradingview TOTAL_MCAP %s -> %s", p.name, n)
                if tot_mcap is None or tot_mcap.empty:
                    tot_mcap = df
    except Exception as e:
        notes.append(f"tradingview TOTAL_MCAP: {e}")

    try:
        if want("BTC.D") and btc_mcap is not None and tot_mcap is not None and not tot_mcap.empty:
            dom = build_dominance_pct(btc_mcap, tot_mcap)
            n = _upsert_daily_series(db, dom, source="coingecko", symbol="BTC.D")
            log.info("upsert BTC.D (from mcaps) -> %s", n)
        if want("ETH.D") and eth_mcap is not None and tot_mcap is not None and not tot_mcap.empty:
            dom = build_dominance_pct(eth_mcap, tot_mcap)
            n = _upsert_daily_series(db, dom, source="coingecko", symbol="ETH.D")
            log.info("upsert ETH.D -> %s", n)
        # If we have BTC.D from TradingView already / via btcd job, derive TOTAL ≈ BTC_MCAP / (BTC.D/100)
        if want("TOTAL_MCAP") and (tot_mcap is None or tot_mcap.empty) and btc_mcap is not None:
            existing = db.load("BTC.D", "1d")
            if existing is not None and not existing.empty:
                import pandas as pd

                left = btc_mcap[["ts_ms", "close"]].rename(columns={"close": "btc"}).sort_values("ts_ms")
                right = existing[["ts_ms", "close"]].rename(columns={"close": "dom"}).sort_values("ts_ms")
                merged = pd.merge_asof(left, right, on="ts_ms", direction="nearest", tolerance=86_400_000)
                tot = (merged["btc"] / (merged["dom"] / 100.0)).to_numpy(dtype=float)
                from botsgeneral.research_candles.fetch_crypto_macro import _close_only

                derived = _close_only(merged["ts_ms"].to_numpy(), tot)
                n = _upsert_daily_series(db, derived, source="derived", symbol="TOTAL_MCAP")
                log.info("upsert derived TOTAL_MCAP from BTC_MCAP/BTC.D -> %s", n)
                tot_mcap = derived
    except Exception as e:
        notes.append(f"dominance: {e}")

    try:
        if any(want(s) for s in ("STABLE_MCAP", "STABLE_FLOW", "USDT_MCAP", "USDC_MCAP", "DAI_MCAP")):
            need_stable = not (
                fresh("defillama", "STABLE_MCAP")
                and (not want("STABLE_FLOW") or fresh("defillama", "STABLE_FLOW"))
            )
            if need_stable:
                stable = fetch_defillama_stable_mcap_daily()
                if want("STABLE_MCAP"):
                    n = _upsert_daily_series(db, stable, source="defillama", symbol="STABLE_MCAP")
                    log.info("upsert defillama STABLE_MCAP -> %s", n)
                if want("STABLE_FLOW") and stable is not None and not stable.empty:
                    flow = stablecoin_flow_from_mcap(stable)
                    n = _upsert_daily_series(db, flow, source="defillama", symbol="STABLE_FLOW")
                    log.info("upsert defillama STABLE_FLOW -> %s", n)
            ids = resolve_stablecoin_ids()
            for canon, _sym in STABLECOIN_SYMBOLS:
                if not want(canon) or fresh("defillama", canon):
                    continue
                aid = ids.get(canon)
                if aid is None:
                    notes.append(f"defillama id missing for {canon}")
                    continue
                df = fetch_defillama_stablecoin_asset_daily(aid, canon)
                n = _upsert_daily_series(db, df, source="defillama", symbol=canon)
                log.info("upsert defillama %s -> %s", canon, n)
                time.sleep(0.3)
    except Exception as e:
        notes.append(f"stablecoins: {e}")

    try:
        if want("FNG") and not fresh("alternative", "FNG"):
            fng = fetch_fear_greed_daily()
            n = _upsert_daily_series(db, fng, source="alternative", symbol="FNG")
            log.info("upsert Fear&Greed FNG -> %s", n)
            if n == 0:
                notes.append("FNG empty")
    except Exception as e:
        notes.append(f"FNG: {e}")

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
    only = only or {"dukascopy", "yahoo", "binance", "btcd", "fred", "crypto_macro"}
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
        all_notes.extend(
            _download_yahoo(db, symbols=symbols, timeframes=timeframes, incremental=incremental)
        )
    if "fred" in only:
        log.info("=== FRED Treasury yields / spreads ===")
        all_notes.extend(_download_fred(db, symbols=symbols, incremental=incremental))
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
    if "crypto_macro" in only:
        log.info("=== Crypto macro (mcap / stables / FNG) ===")
        all_notes.extend(_download_crypto_macro(db, symbols=symbols, incremental=incremental))

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
        default="dukascopy,yahoo,binance,btcd,fred,crypto_macro",
        help="Comma list: dukascopy,yahoo,binance,btcd,fred,crypto_macro",
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
